"""Multimodal use-cases (Phase 4): extract tables and embedded images in the background, persist them page by
page so progress is visible, and serve them back with their source location.

Same robustness pattern as text processing: atomic claim, per-page commits, a terminal status on every path,
startup recovery of interrupted runs, files only ever read/written inside their configured directory.
"""

import logging
import os
import re
import shutil
import time
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
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
from app.models.document_table import DocumentTable, TableCell
from app.schemas.multimodal import (
    BoxOut,
    CellOut,
    ImageDetail,
    ImageSummary,
    MultimodalStatusOut,
    RegionOut,
    TableDetail,
    TableSummary,
)
from app.services.clinical_reset import reset_clinical
from app.services.processing import resolve_stored_path
from document_processing import (
    IMG_OCR_UNAVAILABLE,
    DocumentProcessingError,
    ImageResult,
    MultimodalProcessor,
    PageMultimodalResult,
    display_region,
)

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = (
    "Table and image extraction was interrupted (the server stopped or restarted). Run it again."
)
_SAFE_FILENAME = re.compile(r"^[0-9a-f-]{36}\.(png|jpg)$")
_MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg"}


# ---------------------------------------------------------------- claim / recovery

def claim_multimodal(session: Session, document_id: uuid.UUID) -> bool:
    """Atomically move a document to `queued`; False if a run is already queued or running."""
    result = session.execute(
        update(Document)
        .where(Document.id == document_id, Document.multimodal_status.notin_(PROCESSING_IN_PROGRESS))
        .values(multimodal_status=PROCESSING_QUEUED, multimodal_error_code=None, multimodal_error=None)
    )
    session.commit()
    return result.rowcount == 1


def recover_interrupted_multimodal(session_factory: sessionmaker) -> int:
    """At startup, mark runs left `queued`/`processing` by a previous process as failed (single-process assumption)."""
    with session_factory() as session:
        result = session.execute(
            update(Document)
            .where(Document.multimodal_status.in_(PROCESSING_IN_PROGRESS))
            .values(
                multimodal_status=PROCESSING_FAILED,
                multimodal_error_code="interrupted",
                multimodal_error=INTERRUPTED_MESSAGE,
            )
        )
        session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------- files

def document_image_dir(settings: Settings, document_id: uuid.UUID) -> Path:
    return settings.image_dir_path / str(document_id)


def resolve_image_file(settings: Settings, image: DocumentImage) -> Path | None:
    """Absolute path of a stored image, or None if unset, malformed, or outside the image directory."""
    if not image.stored_filename or not _SAFE_FILENAME.match(image.stored_filename):
        return None
    base = settings.image_dir_path.resolve()
    candidate = (base / str(image.document_id) / image.stored_filename).resolve()
    return candidate if base in candidate.parents else None


def media_type_for(stored_format: str | None) -> str | None:
    return _MEDIA_TYPES.get(stored_format or "")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    os.replace(partial, path)


def _remove_document_images(settings: Settings, document_id: uuid.UUID) -> None:
    directory = document_image_dir(settings, document_id).resolve()
    base = settings.image_dir_path.resolve()
    if base in directory.parents and directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------- background run

def run_multimodal(
    session_factory: sessionmaker, settings: Settings, document_id: uuid.UUID, image_ocr: bool | None = None
) -> None:
    """Background entry point. Never raises; always leaves a terminal status behind."""
    started = time.monotonic()
    with session_factory() as session:
        try:
            _run(session, settings, document_id, image_ocr)
        except Exception:
            logger.exception("Unexpected error while extracting tables/images for document %s", document_id)
            session.rollback()
            _mark_failed(session, document_id, "internal_error", "Extraction failed unexpectedly. See the server log.")
    logger.info("Multimodal processing finished for document %s in %.2fs", document_id, time.monotonic() - started)


def _mark_failed(session: Session, document_id: uuid.UUID, code: str, message: str) -> None:
    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            multimodal_status=PROCESSING_FAILED,
            multimodal_error_code=code,
            multimodal_error=message,
            multimodal_processed_at=utcnow(),
        )
    )
    session.commit()


def _clear_previous(session: Session, settings: Settings, document_id: uuid.UUID) -> None:
    table_ids = select(DocumentTable.id).where(DocumentTable.document_id == document_id)
    session.execute(delete(TableCell).where(TableCell.table_id.in_(table_ids)))
    session.execute(delete(DocumentTable).where(DocumentTable.document_id == document_id))
    session.execute(delete(DocumentImage).where(DocumentImage.document_id == document_id))
    reset_clinical(session, document_id)  # evidence that points at the old tables/images is stale
    session.commit()
    _remove_document_images(settings, document_id)


class _Tally:
    def __init__(self) -> None:
        self.tables = 0
        self.images = 0
        self.pages = 0
        self.pages_with_errors = 0
        self.first_error: str | None = None
        self.ocr_unavailable = False
        self.counts: Counter[str] = Counter()

    def add(self, result: PageMultimodalResult) -> None:
        self.pages += 1
        self.tables += len(result.tables)
        self.images += len(result.images)
        if result.errors:
            self.pages_with_errors += 1
            self.first_error = self.first_error or result.errors[0]
        self.ocr_unavailable = self.ocr_unavailable or any(i.ocr_status == IMG_OCR_UNAVAILABLE for i in result.images)
        self.counts["tables_skipped_empty"] += result.tables_skipped_empty
        self.counts["tables_skipped_over_limit"] += result.tables_skipped_over_limit
        self.counts["images_skipped_small"] += result.images_skipped_small
        self.counts["images_skipped_over_limit"] += result.images_skipped_over_limit

    def fail_page(self, message: str) -> None:
        self.pages += 1
        self.pages_with_errors += 1
        self.first_error = self.first_error or message


def _run(session: Session, settings: Settings, document_id: uuid.UUID, image_ocr: bool | None) -> None:
    document = session.get(Document, document_id)
    if document is None:
        logger.warning("Document %s disappeared before multimodal processing", document_id)
        return

    document.multimodal_status = PROCESSING_RUNNING
    document.multimodal_page_count = None
    document.multimodal_pages_processed = 0
    document.multimodal_processed_at = None
    document.table_count = None
    document.image_count = None
    document.multimodal_summary = None
    session.commit()
    _clear_previous(session, settings, document_id)

    path = resolve_stored_path(settings, document)
    if path is None or not path.is_file():
        _mark_failed(session, document_id, "file_missing", "The stored file could not be found on the server.")
        return

    effective_image_ocr = settings.image_ocr if image_ocr is None else image_ocr
    tally = _Tally()
    try:
        with MultimodalProcessor(path, settings.processing_config, image_ocr=effective_image_ocr) as processor:
            document.multimodal_page_count = processor.page_count
            session.commit()
            for result in processor.iter_pages():
                _persist_page(session, settings, document, result, tally)
    except DocumentProcessingError as exc:
        session.rollback()
        _clear_previous(session, settings, document_id)
        _mark_failed(session, document_id, exc.code, exc.message)
        return

    _finalize(session, document_id, tally, effective_image_ocr)


def _persist_page(
    session: Session, settings: Settings, document: Document, result: PageMultimodalResult, tally: _Tally
) -> None:
    """Store one page's tables and images (rows + files) and commit, so progress is visible."""
    written: list[Path] = []
    try:
        for table in result.tables:
            row = DocumentTable(
                document_id=document.id,
                page_number=table.page_number,
                table_index=table.table_index,
                detection_method=table.detection_method,
                bbox_x0=table.bbox[0], bbox_y0=table.bbox[1], bbox_x1=table.bbox[2], bbox_y1=table.bbox[3],
                page_width=table.page_width,
                page_height=table.page_height,
                page_rotation=table.page_rotation,
                row_count=table.row_count,
                col_count=table.col_count,
            )
            for cell in table.cells:
                box = cell.bbox
                row.cells.append(
                    TableCell(
                        row_index=cell.row_index,
                        col_index=cell.col_index,
                        text=cell.text,
                        bbox_x0=box[0] if box else None, bbox_y0=box[1] if box else None,
                        bbox_x1=box[2] if box else None, bbox_y1=box[3] if box else None,
                    )
                )
            session.add(row)
        for image in result.images:
            session.add(_image_row(settings, document.id, image, written))
        document.multimodal_pages_processed = (document.multimodal_pages_processed or 0) + 1
        session.commit()
        tally.add(result)
    except Exception:
        logger.exception("Could not store tables/images of page %d of document %s", result.page_number, document.id)
        session.rollback()
        for file in written:
            file.unlink(missing_ok=True)
        document.multimodal_pages_processed = (document.multimodal_pages_processed or 0) + 1
        session.commit()
        tally.fail_page(f"Results for page {result.page_number} could not be saved.")


def _image_row(settings: Settings, document_id: uuid.UUID, image: ImageResult, written: list[Path]) -> DocumentImage:
    image_id = uuid.uuid4()
    stored_filename = None
    if image.data:
        extension = "jpg" if image.stored_format == "jpeg" else "png"
        stored_filename = f"{image_id}.{extension}"
        target = document_image_dir(settings, document_id) / stored_filename
        _write_atomic(target, image.data)
        written.append(target)
    box = image.bbox
    return DocumentImage(
        id=image_id,
        document_id=document_id,
        page_number=image.page_number,
        image_index=image.image_index,
        xref=image.xref,
        width_px=image.width_px,
        height_px=image.height_px,
        colorspace=image.colorspace,
        bits_per_component=image.bits_per_component,
        original_format=image.original_format,
        stored_format=image.stored_format,
        stored_filename=stored_filename,
        file_size_bytes=len(image.data) if image.data else None,
        sha256=image.sha256,
        bbox_x0=box[0] if box else None, bbox_y0=box[1] if box else None,
        bbox_x1=box[2] if box else None, bbox_y1=box[3] if box else None,
        page_width=image.page_width,
        page_height=image.page_height,
        page_rotation=image.page_rotation,
        is_full_page=image.is_full_page,
        extraction_status=image.status,
        error_message=image.error_message,
        ocr_status=image.ocr_status,
        ocr_text=image.ocr_text,
        ocr_mean_confidence=image.ocr_mean_confidence,
    )


def _finalize(session: Session, document_id: uuid.UUID, tally: _Tally, image_ocr: bool) -> None:
    failed_images = session.scalar(
        select(func.count()).select_from(DocumentImage).where(
            DocumentImage.document_id == document_id, DocumentImage.extraction_status == "failed"
        )
    ) or 0

    status, code, message = PROCESSING_COMPLETED, None, None
    problems: list[str] = []
    if tally.pages_with_errors:
        code = "ocr_unavailable" if tally.ocr_unavailable else "page_errors"
        problems.append(f"{tally.pages_with_errors} page(s) had problems. First: {tally.first_error}")
    if failed_images:
        code = code or "image_errors"
        problems.append(f"{failed_images} image(s) could not be extracted (see each image's message).")
    if problems:
        message = " ".join(problems)
        status = (
            PROCESSING_FAILED
            if tally.pages and tally.pages_with_errors == tally.pages and not (tally.tables or tally.images)
            else PROCESSING_COMPLETED_WITH_ERRORS
        )

    summary = {**{k: int(v) for k, v in tally.counts.items()}, "image_ocr_requested": image_ocr}
    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            multimodal_status=status,
            multimodal_error_code=code,
            multimodal_error=message,
            multimodal_processed_at=utcnow(),
            table_count=tally.tables,
            image_count=tally.images,
            multimodal_summary=summary,
        )
    )
    session.commit()


def run_pipeline(session_factory: sessionmaker, settings: Settings, document_id: uuid.UUID) -> None:
    """Text extraction + OCR, then (each switchable) tables/images and clinical extraction.

    The stages have separate statuses; a later-stage problem never changes an earlier stage's status."""
    from app.services import clinical as clinical_service  # local imports keep dependencies one-way at import time
    from app.services.processing import run_processing

    run_processing(session_factory, settings, document_id)
    if settings.auto_multimodal:
        try:
            with session_factory() as session:
                document = session.get(Document, document_id)
                if document is None or document.processing_status == PROCESSING_FAILED:
                    return
                if claim_multimodal(session, document_id):
                    claimed = True
                else:
                    claimed = False  # a manual run is already in progress
            if claimed:
                run_multimodal(session_factory, settings, document_id)
        except Exception:
            logger.exception("Automatic table/image extraction could not start for document %s", document_id)
    if settings.auto_clinical_extraction:
        try:
            with session_factory() as session:
                document = session.get(Document, document_id)
                if document is None or not clinical_service.can_run(document):
                    return
                claimed = clinical_service.claim_clinical(session, document_id)
            if claimed:
                clinical_service.run_clinical(session_factory, settings, document_id)
        except Exception:
            logger.exception("Automatic clinical extraction could not start for document %s", document_id)


# ---------------------------------------------------------------- read side

def build_status(session: Session, document: Document) -> MultimodalStatusOut:
    by_status = dict(
        session.execute(
            select(DocumentImage.extraction_status, func.count())
            .where(DocumentImage.document_id == document.id)
            .group_by(DocumentImage.extraction_status)
        ).all()
    )
    by_ocr = dict(
        session.execute(
            select(DocumentImage.ocr_status, func.count())
            .where(DocumentImage.document_id == document.id)
            .group_by(DocumentImage.ocr_status)
        ).all()
    )
    pages_with_tables = session.scalar(
        select(func.count(func.distinct(DocumentTable.page_number))).where(DocumentTable.document_id == document.id)
    ) or 0
    pages_with_images = session.scalar(
        select(func.count(func.distinct(DocumentImage.page_number))).where(DocumentImage.document_id == document.id)
    ) or 0
    return MultimodalStatusOut(
        document_id=document.id,
        multimodal_status=document.multimodal_status,
        page_count=document.multimodal_page_count,
        pages_processed=document.multimodal_pages_processed or 0,
        table_count=document.table_count,
        image_count=document.image_count,
        images_by_status={k: int(v) for k, v in by_status.items()},
        images_by_ocr_status={k: int(v) for k, v in by_ocr.items()},
        pages_with_tables=int(pages_with_tables),
        pages_with_images=int(pages_with_images),
        summary=document.multimodal_summary,
        error_code=document.multimodal_error_code,
        error_message=document.multimodal_error,
        processed_at=document.multimodal_processed_at,
    )


def _region(box: tuple[float, float, float, float], width: float, height: float, rotation: int) -> RegionOut:
    x, y, w, h = display_region(box, width, height, rotation)
    return RegionOut(x=x, y=y, width=w, height=h)


def _box_out(x0, y0, x1, y1) -> BoxOut | None:
    if None in (x0, y0, x1, y1):
        return None
    return BoxOut(x0=x0, y0=y0, x1=x1, y1=y1)


def table_summary(row: DocumentTable) -> TableSummary:
    box = (row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1)
    return TableSummary(
        id=row.id,
        document_id=row.document_id,
        page_number=row.page_number,
        table_index=row.table_index,
        detection_method=row.detection_method,
        row_count=row.row_count,
        col_count=row.col_count,
        bbox=BoxOut(x0=box[0], y0=box[1], x1=box[2], y1=box[3]),
        region=_region(box, row.page_width, row.page_height, row.page_rotation),
        page_width=row.page_width,
        page_height=row.page_height,
        page_rotation=row.page_rotation,
    )


def table_detail(row: DocumentTable) -> TableDetail:
    grid: list[list[str | None]] = [[None] * row.col_count for _ in range(row.row_count)]
    cells: list[CellOut] = []
    for cell in row.cells:
        if cell.row_index < row.row_count and cell.col_index < row.col_count:
            grid[cell.row_index][cell.col_index] = cell.text
        cells.append(
            CellOut(
                id=cell.id,
                row_index=cell.row_index,
                col_index=cell.col_index,
                text=cell.text,
                bbox=_box_out(cell.bbox_x0, cell.bbox_y0, cell.bbox_x1, cell.bbox_y1),
            )
        )
    return TableDetail(**table_summary(row).model_dump(), cells=cells, rows=grid)


def _image_fields(row: DocumentImage) -> dict:
    box = _box_out(row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1)
    region = (
        _region((row.bbox_x0, row.bbox_y0, row.bbox_x1, row.bbox_y1), row.page_width, row.page_height, row.page_rotation)
        if box
        else None
    )
    return dict(
        id=row.id,
        document_id=row.document_id,
        page_number=row.page_number,
        image_index=row.image_index,
        width_px=row.width_px,
        height_px=row.height_px,
        colorspace=row.colorspace,
        bits_per_component=row.bits_per_component,
        original_format=row.original_format,
        stored_format=row.stored_format,
        file_size_bytes=row.file_size_bytes,
        sha256=row.sha256,
        bbox=box,
        region=region,
        page_width=row.page_width,
        page_height=row.page_height,
        page_rotation=row.page_rotation,
        is_full_page=row.is_full_page,
        extraction_status=row.extraction_status,
        error_message=row.error_message,
        ocr_status=row.ocr_status,
        ocr_char_count=len("".join((row.ocr_text or "").split())),
        ocr_mean_confidence=row.ocr_mean_confidence,
        has_file=bool(row.stored_filename),
    )


def image_summary(row: DocumentImage) -> ImageSummary:
    return ImageSummary(**_image_fields(row))


def image_detail(row: DocumentImage) -> ImageDetail:
    return ImageDetail(**_image_fields(row), ocr_text=row.ocr_text)


def list_tables(session: Session, document_id: uuid.UUID, page_number: int | None = None) -> list[DocumentTable]:
    query = select(DocumentTable).where(DocumentTable.document_id == document_id)
    if page_number is not None:
        query = query.where(DocumentTable.page_number == page_number)
    return list(session.scalars(query.order_by(DocumentTable.page_number, DocumentTable.table_index)))


def get_table(session: Session, document_id: uuid.UUID, table_id: uuid.UUID) -> DocumentTable | None:
    return session.scalar(
        select(DocumentTable).where(DocumentTable.document_id == document_id, DocumentTable.id == table_id)
    )


def list_images(session: Session, document_id: uuid.UUID, page_number: int | None = None) -> list[DocumentImage]:
    query = select(DocumentImage).where(DocumentImage.document_id == document_id)
    if page_number is not None:
        query = query.where(DocumentImage.page_number == page_number)
    return list(session.scalars(query.order_by(DocumentImage.page_number, DocumentImage.image_index)))


def get_image(session: Session, document_id: uuid.UUID, image_id: uuid.UUID) -> DocumentImage | None:
    return session.scalar(
        select(DocumentImage).where(DocumentImage.document_id == document_id, DocumentImage.id == image_id)
    )
