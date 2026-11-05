"""Processing use-cases: claim a document, run the extraction pipeline in the background,
and report status. Persists page results as they are produced so progress is visible."""

import logging
import time
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.services.clinical_reset import reset_clinical
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
from app.models.document_page import DocumentPage
from app.schemas.processing import ProcessingStatusOut
from document_processing import (
    PAGE_FAILED,
    PAGE_NEEDS_OCR,
    DocumentProcessingError,
    PageResult,
    PdfProcessor,
)

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Processing was interrupted (the server stopped or restarted). Run processing again."


def claim_for_processing(session: Session, document_id: uuid.UUID) -> bool:
    """Atomically move a document to `queued`; False if it is already queued or running."""
    result = session.execute(
        update(Document)
        .where(Document.id == document_id, Document.processing_status.notin_(PROCESSING_IN_PROGRESS))
        .values(processing_status=PROCESSING_QUEUED, processing_error_code=None, processing_error=None)
    )
    session.commit()
    return result.rowcount == 1


def recover_interrupted(session_factory: sessionmaker) -> int:
    """At startup, mark documents left `queued`/`processing` by a previous run as failed.

    Assumes a single backend process (see docs/limitations.md)."""
    with session_factory() as session:
        result = session.execute(
            update(Document)
            .where(Document.processing_status.in_(PROCESSING_IN_PROGRESS))
            .values(
                processing_status=PROCESSING_FAILED,
                processing_error_code="interrupted",
                processing_error=INTERRUPTED_MESSAGE,
            )
        )
        session.commit()
        return result.rowcount or 0


def resolve_stored_path(settings: Settings, document: Document) -> Path | None:
    """Absolute path of the stored file, or None if it would fall outside the upload directory."""
    base = settings.upload_dir_path.resolve()
    candidate = (base / document.storage_path).resolve()
    return candidate if base in candidate.parents else None


def run_processing(session_factory: sessionmaker, settings: Settings, document_id: uuid.UUID) -> None:
    """Background entry point. Never raises; always leaves a terminal status behind."""
    started = time.monotonic()
    with session_factory() as session:
        try:
            _run(session, settings, document_id)
        except Exception:
            logger.exception("Unexpected error while processing document %s", document_id)
            session.rollback()
            _mark_failed(session, document_id, "internal_error", "Processing failed unexpectedly. See the server log.")
    logger.info("Processing finished for document %s in %.2fs", document_id, time.monotonic() - started)


def _mark_failed(session: Session, document_id: uuid.UUID, code: str, message: str) -> None:
    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            processing_status=PROCESSING_FAILED,
            processing_error_code=code,
            processing_error=message,
            processed_at=utcnow(),
        )
    )
    session.commit()


def _run(session: Session, settings: Settings, document_id: uuid.UUID) -> None:
    document = session.get(Document, document_id)
    if document is None:
        logger.warning("Document %s disappeared before processing", document_id)
        return

    document.processing_status = PROCESSING_RUNNING
    document.page_count = None
    document.pdf_metadata = None
    document.processed_at = None
    session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    reset_clinical(session, document_id)  # evidence derived from the old pages is stale
    session.commit()

    path = resolve_stored_path(settings, document)
    if path is None or not path.is_file():
        _mark_failed(session, document_id, "file_missing", "The stored file could not be found on the server.")
        return

    tally: list[PageResult] = []
    try:
        with PdfProcessor(path, settings.processing_config) as processor:
            document.page_count = processor.page_count
            document.pdf_metadata = processor.metadata or None
            session.commit()
            for result in processor.iter_pages():
                session.add(_to_row(document_id, result))
                session.commit()  # per page, so the status API shows live progress
                tally.append(result)
    except DocumentProcessingError as exc:
        session.rollback()
        # Keep nothing partial for a document that could not be opened.
        session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        _mark_failed(session, document_id, exc.code, exc.message)
        return

    _finalize(session, document_id, tally)


def _to_row(document_id: uuid.UUID, r: PageResult) -> DocumentPage:
    return DocumentPage(
        document_id=document_id,
        page_number=r.page_number,
        extraction_method=r.extraction_method,
        extracted_text=r.text,
        char_count=r.char_count,
        processing_status=r.status,
        ocr_status=r.ocr_status,
        ocr_mean_confidence=r.ocr_mean_confidence,
        has_images=r.has_images,
        is_likely_scanned=r.is_likely_scanned,
        error_message=r.error_message,
    )


def _finalize(session: Session, document_id: uuid.UUID, results: list[PageResult]) -> None:
    needs_ocr = [r for r in results if r.status == PAGE_NEEDS_OCR]
    failed = [r for r in results if r.status == PAGE_FAILED]

    status, code, message = PROCESSING_COMPLETED, None, None
    if needs_ocr or failed:
        parts: list[str] = []
        if needs_ocr:
            code = "ocr_unavailable"
            parts.append(
                f"{len(needs_ocr)} page(s) have no text layer and need OCR, but OCR could not run: "
                f"{needs_ocr[0].error_message}"
            )
        if failed:
            code = code or "page_errors"
            parts.append(f"{len(failed)} page(s) failed: {failed[0].error_message}")
        message = " ".join(parts)
        status = PROCESSING_FAILED if len(failed) == len(results) else PROCESSING_COMPLETED_WITH_ERRORS

    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            processing_status=status,
            processing_error_code=code,
            processing_error=message,
            processed_at=utcnow(),
        )
    )
    session.commit()


# ---- read side ----


def build_status(session: Session, document: Document) -> ProcessingStatusOut:
    rows = session.execute(
        select(
            DocumentPage.extraction_method,
            DocumentPage.processing_status,
            DocumentPage.ocr_status,
            DocumentPage.is_likely_scanned,
        ).where(DocumentPage.document_id == document.id)
    ).all()
    return ProcessingStatusOut(
        document_id=document.id,
        processing_status=document.processing_status,
        page_count=document.page_count,
        pages_processed=len(rows),
        pages_by_method=dict(Counter(r[0] for r in rows)),
        pages_by_status=dict(Counter(r[1] for r in rows)),
        pages_by_ocr_status=dict(Counter(r[2] for r in rows)),
        likely_scanned_pages=sum(1 for r in rows if r[3]),
        error_code=document.processing_error_code,
        error_message=document.processing_error,
        processed_at=document.processed_at,
    )


def list_pages(session: Session, document_id: uuid.UUID) -> list[DocumentPage]:
    return list(
        session.scalars(
            select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)
        )
    )


def get_page(session: Session, document_id: uuid.UUID, page_number: int) -> DocumentPage | None:
    return session.scalar(
        select(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.page_number == page_number)
    )
