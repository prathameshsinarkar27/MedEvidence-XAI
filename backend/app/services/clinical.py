"""Clinical information extraction use-cases (Phase 5).

Reads what Phases 3-4 stored (page text, tables, image OCR text), runs the pure-Python `clinical_extraction`
library, and stores one ClinicalEvidence row per extracted fact, page by page so progress is visible.
Same robustness pattern as the earlier stages: atomic claim, per-page commits, a terminal status on every path,
startup recovery, generic error messages. Nothing here retrieves, verifies or answers (Phases 6-9).
"""

import logging
import time
import uuid
from collections import Counter

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import (
    PROCESSING_COMPLETED,
    PROCESSING_COMPLETED_WITH_ERRORS,
    PROCESSING_FAILED,
    PROCESSING_IN_PROGRESS,
    PROCESSING_QUEUED,
    PROCESSING_RUNNING,
    Document,
    utcnow,
)
from app.models.document_image import DocumentImage
from app.models.document_page import DocumentPage
from app.models.document_table import DocumentTable
from app.schemas.clinical import ClinicalStatusOut, EvidenceOut
from app.schemas.multimodal import BoxOut, RegionOut
from app.services.clinical_reset import reset_clinical
from app.services.processing import resolve_stored_path
from clinical_extraction import EXTRACTOR_VERSION, Evidence, TableInput, extract_table_evidence, extract_text_evidence
from clinical_extraction.locator import PageLocator, build_page_locator
from clinical_extraction.models import MODALITY_IMAGE_OCR, MODALITY_OCR, MODALITY_TEXT
from document_processing import DocumentProcessingError, display_region
from document_processing.models import METHOD_OCR, METHOD_PDFPLUMBER, METHOD_PYMUPDF
from document_processing.pdf_open import open_pdf

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Clinical extraction was interrupted (the server stopped or restarted). Run it again."
READY_TEXT_STATUSES = (PROCESSING_COMPLETED, PROCESSING_COMPLETED_WITH_ERRORS)
NOTE = (
    "Extraction is rule-based. The confidence value is a heuristic score, not a probability, and extraction "
    "accuracy has not been evaluated. Not yet evaluated. Research prototype - not for clinical use."
)
_INSIDE_FRACTION = 0.8


# ---------------------------------------------------------------- claim / recovery

def can_run(document: Document) -> bool:
    return document.processing_status in READY_TEXT_STATUSES


def claim_clinical(session: Session, document_id: uuid.UUID) -> bool:
    """Atomically move a document to `queued`; False if a run is already queued or running."""
    result = session.execute(
        update(Document)
        .where(Document.id == document_id, Document.clinical_status.notin_(PROCESSING_IN_PROGRESS))
        .values(clinical_status=PROCESSING_QUEUED, clinical_error_code=None, clinical_error=None)
    )
    session.commit()
    return result.rowcount == 1


def recover_interrupted_clinical(session_factory: sessionmaker) -> int:
    with session_factory() as session:
        result = session.execute(
            update(Document)
            .where(Document.clinical_status.in_(PROCESSING_IN_PROGRESS))
            .values(clinical_status=PROCESSING_FAILED, clinical_error_code="interrupted", clinical_error=INTERRUPTED_MESSAGE)
        )
        session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------- background run

def run_clinical(session_factory: sessionmaker, settings: Settings, document_id: uuid.UUID) -> None:
    """Background entry point. Never raises; always leaves a terminal status behind."""
    started = time.monotonic()
    with session_factory() as session:
        try:
            _run(session, settings, document_id)
        except Exception:
            logger.exception("Unexpected error during clinical extraction for document %s", document_id)
            session.rollback()
            _mark_failed(session, document_id, "internal_error", "Extraction failed unexpectedly. See the server log.")
    logger.info("Clinical extraction finished for document %s in %.2fs", document_id, time.monotonic() - started)


def _mark_failed(session: Session, document_id: uuid.UUID, code: str, message: str) -> None:
    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(clinical_status=PROCESSING_FAILED, clinical_error_code=code, clinical_error=message, clinical_processed_at=utcnow())
    )
    session.commit()


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _inside_fraction(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> float:
    ix0, iy0, ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1]), min(inner[2], outer[2]), min(inner[3], outer[3])
    area = max(inner[2] - inner[0], 0.0) * max(inner[3] - inner[1], 0.0)
    if area <= 0 or ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return ((ix1 - ix0) * (iy1 - iy0)) / area


class _Tally:
    def __init__(self) -> None:
        self.pages = 0
        self.pages_with_errors = 0
        self.first_error: str | None = None
        self.evidence = 0
        self.ordinal = 0
        self.truncated = False
        self.counts: Counter[str] = Counter()

    def fail_page(self, message: str) -> None:
        self.pages += 1
        self.pages_with_errors += 1
        self.first_error = self.first_error or message


def _run(session: Session, settings: Settings, document_id: uuid.UUID) -> None:
    document = session.get(Document, document_id)
    if document is None:
        logger.warning("Document %s disappeared before clinical extraction", document_id)
        return

    session.execute(delete(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id))
    document.clinical_status = PROCESSING_RUNNING
    document.clinical_page_count = None
    document.clinical_pages_processed = 0
    document.clinical_processed_at = None
    document.evidence_count = None
    document.clinical_summary = None
    session.commit()

    if document.processing_status not in READY_TEXT_STATUSES:
        _mark_failed(session, document_id, "text_not_processed", "Text extraction has not completed for this document.")
        return

    pages = list(session.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)))
    tables_by_page: dict[int, list[DocumentTable]] = {}
    for table in session.scalars(select(DocumentTable).where(DocumentTable.document_id == document_id).order_by(DocumentTable.page_number, DocumentTable.table_index)):
        tables_by_page.setdefault(table.page_number, []).append(table)
    images_by_page: dict[int, list[DocumentImage]] = {}
    for image in session.scalars(select(DocumentImage).where(DocumentImage.document_id == document_id).order_by(DocumentImage.page_number, DocumentImage.image_index)):
        images_by_page.setdefault(image.page_number, []).append(image)

    document.clinical_page_count = len(pages)
    session.commit()

    pdf = None
    path = resolve_stored_path(settings, document)
    if path is not None and path.is_file():
        try:
            pdf = open_pdf(path, settings.processing_config)
        except DocumentProcessingError:
            pdf = None  # evidence is still produced; it just has no page regions for text mentions
    tally = _Tally()
    tally.counts["tables_available"] = sum(len(v) for v in tables_by_page.values())
    try:
        for page in pages:
            try:
                _process_page(session, settings, document, page, tables_by_page.get(page.page_number, []),
                              images_by_page.get(page.page_number, []), pdf, tally)
            except Exception:
                logger.exception("Clinical extraction failed on page %d of document %s", page.page_number, document_id)
                session.rollback()
                session.execute(delete(ClinicalEvidence).where(
                    ClinicalEvidence.document_id == document_id, ClinicalEvidence.page_number == page.page_number))
                tally.evidence = session.scalar(select(func.count()).select_from(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id)) or 0
                document = session.get(Document, document_id)
                document.clinical_pages_processed = (document.clinical_pages_processed or 0) + 1
                session.commit()
                tally.fail_page(f"Page {page.page_number} could not be analysed.")
    finally:
        if pdf is not None:
            pdf.close()
    _finalize(session, document_id, tally, pdf is not None)


def _process_page(session, settings, document, page, tables, images, pdf, tally: _Tally) -> None:
    rows: list[ClinicalEvidence] = []

    # ---- text / OCR of the page
    text_items: list[Evidence] = []
    if page.extraction_method in (METHOD_PYMUPDF, METHOD_PDFPLUMBER) and page.extracted_text.strip():
        text_items = extract_text_evidence(page.extracted_text, MODALITY_TEXT)
    elif page.extraction_method == METHOD_OCR and page.extracted_text.strip():
        text_items = extract_text_evidence(page.extracted_text, MODALITY_OCR, page.ocr_mean_confidence)
    else:
        tally.counts["pages_without_text"] += 1

    locator: PageLocator | None = None
    if text_items and pdf is not None and page.extraction_method in (METHOD_PYMUPDF, METHOD_PDFPLUMBER):
        try:
            locator = build_page_locator(pdf[page.page_number - 1], page.extracted_text)
        except Exception:
            locator = None
        tally.counts["text_pages_located" if locator else "text_pages_not_located"] += 1

    # ---- tables
    table_boxes: dict[uuid.UUID, tuple[float, float, float, float]] = {}
    table_evidence: list[tuple[DocumentTable, Evidence, tuple | None]] = []
    table_keys: dict[uuid.UUID, set] = {}
    for table in tables:
        grid: list[list[str | None]] = [[None] * table.col_count for _ in range(table.row_count)]
        cell_boxes: dict[tuple[int, int], tuple] = {}
        for cell in table.cells:
            if cell.row_index < table.row_count and cell.col_index < table.col_count:
                grid[cell.row_index][cell.col_index] = cell.text
                if None not in (cell.bbox_x0, cell.bbox_y0, cell.bbox_x1, cell.bbox_y1):
                    cell_boxes[(cell.row_index, cell.col_index)] = (cell.bbox_x0, cell.bbox_y0, cell.bbox_x1, cell.bbox_y1)
        table_box = (table.bbox_x0, table.bbox_y0, table.bbox_x1, table.bbox_y1)
        table_boxes[table.id] = table_box
        items, stats = extract_table_evidence(TableInput(table.id, grid))
        tally.counts["tables_used"] += 1
        tally.counts["table_rows_extracted"] += stats["rows_extracted"]
        tally.counts["table_rows_unrecognised"] += stats["rows_unrecognised"]
        keys = set()
        for ev in items:
            box = _union([cell_boxes[p] for p in ev.cell_positions if p in cell_boxes]) or table_box
            table_evidence.append((table, ev, box))
            keys.add((ev.entity_type, ev.entity_name, ev.value_numeric))
        table_keys[table.id] = keys

    # ---- drop text duplicates of rows the table extractor already captured
    kept_text: list[tuple[Evidence, tuple | None]] = []
    for ev in text_items:
        box = locator.locate(ev.char_start, ev.char_end) if locator and ev.char_start is not None else None
        duplicate = False
        if box is not None and ev.entity_type in ("lab_result", "vital_sign", "medication"):
            for table_id, table_box in table_boxes.items():
                if _inside_fraction(box, table_box) >= _INSIDE_FRACTION and (
                        ev.entity_type, ev.entity_name, ev.value_numeric) in table_keys.get(table_id, set()):
                    duplicate = True
                    break
        if duplicate:
            tally.counts["text_duplicates_of_table_rows_suppressed"] += 1
        else:
            kept_text.append((ev, box))

    for ev, box in kept_text:
        rows.append(_row(document.id, page.page_number, ev, box, locator.page_width if locator else None,
                         locator.page_height if locator else None, locator.page_rotation if locator else None))
    for table, ev, box in table_evidence:
        rows.append(_row(document.id, page.page_number, ev, box, table.page_width, table.page_height, table.page_rotation,
                         table_id=table.id))

    # ---- OCR text of embedded images (full-page images are skipped: the page OCR already covers them)
    for image in images:
        if image.ocr_status != "completed" or not image.ocr_text or not image.ocr_text.strip() or image.is_full_page:
            continue
        items = extract_text_evidence(image.ocr_text, MODALITY_IMAGE_OCR, image.ocr_mean_confidence)
        if items:
            tally.counts["image_ocr_texts_used"] += 1
        box = None if None in (image.bbox_x0, image.bbox_y0, image.bbox_x1, image.bbox_y1) else (
            image.bbox_x0, image.bbox_y0, image.bbox_x1, image.bbox_y1)
        for ev in items:
            rows.append(_row(document.id, page.page_number, ev, box, image.page_width, image.page_height, image.page_rotation,
                             image_id=image.id))

    rows.sort(key=lambda r: (r.modality == "image_ocr", r.char_start if r.char_start is not None else 10**9))  # stable, deterministic
    limit = settings.max_evidence_per_document
    for row in rows:
        if tally.evidence >= limit:
            tally.truncated = True
            break
        tally.ordinal += 1
        row.ordinal = tally.ordinal
        tally.evidence += 1
        session.add(row)
    document.clinical_pages_processed = (document.clinical_pages_processed or 0) + 1
    session.commit()
    tally.pages += 1


def _row(document_id, page_number, ev: Evidence, box, page_width, page_height, page_rotation, *, table_id=None, image_id=None) -> ClinicalEvidence:
    placed = box is not None and page_width is not None
    return ClinicalEvidence(
        document_id=document_id,
        page_number=page_number,
        ordinal=0,
        modality=ev.modality,
        entity_type=ev.entity_type,
        entity_name=ev.entity_name,
        assertion=ev.assertion,
        mention_text=ev.mention_text,
        source_text=ev.source_text,
        source_field=ev.source_field,
        char_start=ev.char_start, char_end=ev.char_end, source_start=ev.source_start, source_end=ev.source_end,
        value_text=ev.value_text, value_numeric=ev.value_numeric, value_comparator=ev.value_comparator,
        unit_text=ev.unit_text, unit_normalized=ev.unit_normalized,
        reference_text=ev.reference_text, reference_low=ev.reference_low, reference_high=ev.reference_high,
        abnormal_flag=ev.abnormal_flag, flag_source=ev.flag_source,
        date_text=ev.date_text, date_iso=ev.date_iso,
        attributes=ev.attributes or {},
        table_id=table_id, table_row_index=ev.row_index,
        cell_positions=[list(p) for p in ev.cell_positions] if ev.cell_positions else None,
        image_id=image_id,
        bbox_x0=box[0] if placed else None, bbox_y0=box[1] if placed else None,
        bbox_x1=box[2] if placed else None, bbox_y1=box[3] if placed else None,
        page_width=page_width if placed else None, page_height=page_height if placed else None,
        page_rotation=page_rotation if placed else None,
        extraction_method=ev.extraction_method,
        extractor_version=EXTRACTOR_VERSION,
        extraction_confidence=ev.confidence,
        confidence_factors=ev.confidence_factors,
        ocr_confidence=ev.ocr_confidence,
    )


def _finalize(session: Session, document_id: uuid.UUID, tally: _Tally, locator_available: bool) -> None:
    status, code, message = PROCESSING_COMPLETED, None, None
    if tally.pages_with_errors:
        code = "page_errors"
        message = f"{tally.pages_with_errors} page(s) had problems. First: {tally.first_error}"
        status = PROCESSING_FAILED if tally.pages_with_errors == tally.pages and not tally.evidence else PROCESSING_COMPLETED_WITH_ERRORS
    if tally.truncated:
        code = code or "evidence_limit_reached"
        message = ((message + " ") if message else "") + "The per-document evidence limit (MAX_EVIDENCE_PER_DOCUMENT) was reached; later findings were not stored."
        if status == PROCESSING_COMPLETED:
            status = PROCESSING_COMPLETED_WITH_ERRORS
    summary = {**{k: int(v) for k, v in tally.counts.items()}, "page_regions_available": locator_available,
               "truncated": tally.truncated, "extractor_version": EXTRACTOR_VERSION}
    session.execute(
        update(Document).where(Document.id == document_id).values(
            clinical_status=status, clinical_error_code=code, clinical_error=message, clinical_processed_at=utcnow(),
            evidence_count=tally.evidence, clinical_summary=summary,
        )
    )
    session.commit()


# ---------------------------------------------------------------- read side

def _counts(session: Session, document_id: uuid.UUID, column) -> dict[str, int]:
    rows = session.execute(select(column, func.count()).where(ClinicalEvidence.document_id == document_id).group_by(column)).all()
    return {k: int(v) for k, v in rows}


def build_status(session: Session, document: Document) -> ClinicalStatusOut:
    return ClinicalStatusOut(
        document_id=document.id,
        clinical_status=document.clinical_status,
        page_count=document.clinical_page_count,
        pages_processed=document.clinical_pages_processed or 0,
        evidence_count=document.evidence_count,
        by_entity_type=_counts(session, document.id, ClinicalEvidence.entity_type),
        by_modality=_counts(session, document.id, ClinicalEvidence.modality),
        by_assertion=_counts(session, document.id, ClinicalEvidence.assertion),
        summary=document.clinical_summary,
        extractor_version=EXTRACTOR_VERSION,
        error_code=document.clinical_error_code,
        error_message=document.clinical_error,
        processed_at=document.clinical_processed_at,
        note=NOTE,
    )


def evidence_out(row: ClinicalEvidence) -> EvidenceOut:
    box = region = None
    if None not in (row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1) and row.page_width:
        raw = (row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1)
        box = BoxOut(x0=raw[0], y0=raw[1], x1=raw[2], y1=raw[3])
        x, y, w, h = display_region(raw, row.page_width, row.page_height, row.page_rotation or 0)
        region = RegionOut(x=x, y=y, width=w, height=h)
    return EvidenceOut(
        evidence_id=row.id, document_id=row.document_id, page_number=row.page_number, modality=row.modality,
        entity_type=row.entity_type, entity_name=row.entity_name, assertion=row.assertion,
        mention_text=row.mention_text, source_text=row.source_text, source_field=row.source_field,
        char_start=row.char_start, char_end=row.char_end, source_start=row.source_start, source_end=row.source_end,
        value_text=row.value_text, value_numeric=row.value_numeric, value_comparator=row.value_comparator,
        unit_text=row.unit_text, unit_normalized=row.unit_normalized,
        reference_text=row.reference_text, reference_low=row.reference_low, reference_high=row.reference_high,
        abnormal_flag=row.abnormal_flag, flag_source=row.flag_source, date_text=row.date_text, date_iso=row.date_iso,
        attributes=row.attributes or {}, table_id=row.table_id, table_row_index=row.table_row_index,
        cell_positions=row.cell_positions or [], image_id=row.image_id, bbox=box, region=region,
        page_width=row.page_width, page_height=row.page_height, page_rotation=row.page_rotation,
        extraction_method=row.extraction_method, extractor_version=row.extractor_version,
        extraction_confidence=row.extraction_confidence, confidence_factors=row.confidence_factors or {},
        ocr_confidence=row.ocr_confidence,
    )


def list_evidence(session: Session, document_id: uuid.UUID, *, entity_type=None, page_number=None, modality=None,
                  assertion=None, min_confidence=None, limit=200, offset=0) -> tuple[int, list[ClinicalEvidence]]:
    query = select(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id)
    for column, value in ((ClinicalEvidence.entity_type, entity_type), (ClinicalEvidence.page_number, page_number),
                          (ClinicalEvidence.modality, modality), (ClinicalEvidence.assertion, assertion)):
        if value is not None:
            query = query.where(column == value)
    if min_confidence is not None:
        query = query.where(ClinicalEvidence.extraction_confidence >= min_confidence)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(ClinicalEvidence.ordinal).limit(limit).offset(offset))
    return int(total), list(rows)


def get_evidence(session: Session, document_id: uuid.UUID, evidence_id: uuid.UUID) -> ClinicalEvidence | None:
    return session.scalar(select(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id, ClinicalEvidence.id == evidence_id))
