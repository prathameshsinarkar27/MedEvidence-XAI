"""Tables, images, source-page preview and multimodal processing (Phase 4)."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_session, get_session_factory
from app.models.document import Document
from app.schemas.multimodal import (
    ImageDetail,
    ImageList,
    MultimodalAccepted,
    MultimodalStatusOut,
    TableDetail,
    TableList,
)
from app.services import documents as document_service
from app.services import multimodal as mm
from app.services.processing import resolve_stored_path
from document_processing import DocumentProcessingError, PdfOpenError, render_page_png

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["multimodal"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _require_document(session: Session, document_id: uuid.UUID) -> Document:
    document = document_service.get_document(session, document_id)
    if document is None:
        raise _error(404, "document_not_found", "Document not found.")
    return document


@router.post(
    "/{document_id}/multimodal",
    response_model=MultimodalAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or restart) table and embedded-image extraction",
)
def start_multimodal(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    image_ocr: bool | None = Query(
        default=None, description="OCR text printed inside extracted images. Defaults to the IMAGE_OCR setting."
    ),
    session: Session = Depends(get_session),
    session_factory: sessionmaker = Depends(get_session_factory),
) -> MultimodalAccepted:
    _require_document(session, document_id)
    if not mm.claim_multimodal(session, document_id):
        raise _error(409, "processing_in_progress", "Tables and images are already being extracted for this document.")
    background_tasks.add_task(mm.run_multimodal, session_factory, get_settings(), document_id, image_ocr)
    return MultimodalAccepted(document_id=document_id, multimodal_status="queued")


@router.get("/{document_id}/multimodal", response_model=MultimodalStatusOut, summary="Table/image extraction status")
def get_multimodal_status(document_id: uuid.UUID, session: Session = Depends(get_session)) -> MultimodalStatusOut:
    return mm.build_status(session, _require_document(session, document_id))


@router.get("/{document_id}/tables", response_model=TableList, summary="Detected tables (no cell contents)")
def list_tables(
    document_id: uuid.UUID,
    page_number: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> TableList:
    _require_document(session, document_id)
    rows = mm.list_tables(session, document_id, page_number)
    return TableList(document_id=document_id, items=[mm.table_summary(r) for r in rows])


@router.get("/{document_id}/tables/{table_id}", response_model=TableDetail, summary="One table with all its cells")
def get_table(document_id: uuid.UUID, table_id: uuid.UUID, session: Session = Depends(get_session)) -> TableDetail:
    _require_document(session, document_id)
    row = mm.get_table(session, document_id, table_id)
    if row is None:
        raise _error(404, "table_not_found", "Table not found.")
    return mm.table_detail(row)


@router.get("/{document_id}/images", response_model=ImageList, summary="Embedded images and their placement")
def list_images(
    document_id: uuid.UUID,
    page_number: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> ImageList:
    _require_document(session, document_id)
    rows = mm.list_images(session, document_id, page_number)
    return ImageList(document_id=document_id, items=[mm.image_summary(r) for r in rows])


@router.get("/{document_id}/images/{image_id}", response_model=ImageDetail, summary="One image's metadata and OCR text")
def get_image(document_id: uuid.UUID, image_id: uuid.UUID, session: Session = Depends(get_session)) -> ImageDetail:
    _require_document(session, document_id)
    row = mm.get_image(session, document_id, image_id)
    if row is None:
        raise _error(404, "image_not_found", "Image not found.")
    return mm.image_detail(row)


@router.get("/{document_id}/images/{image_id}/file", summary="The extracted image file (PNG or JPEG)")
def get_image_file(document_id: uuid.UUID, image_id: uuid.UUID, session: Session = Depends(get_session)):
    _require_document(session, document_id)
    row = mm.get_image(session, document_id, image_id)
    if row is None:
        raise _error(404, "image_not_found", "Image not found.")
    media_type = mm.media_type_for(row.stored_format)
    path = mm.resolve_image_file(get_settings(), row)
    if media_type is None or path is None or not path.is_file():
        raise _error(404, "image_file_missing", "No image file is stored for this image.")
    # Content comes from an untrusted PDF: fixed media type, no sniffing, never executed as a page.
    return FileResponse(
        path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.get("/{document_id}/pages/{page_number}/preview", summary="PNG of the source page (for source-region views)")
def get_page_preview(
    document_id: uuid.UUID,
    page_number: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> Response:
    document = _require_document(session, document_id)
    settings = get_settings()
    path = resolve_stored_path(settings, document)
    if path is None or not path.is_file():
        raise _error(404, "file_missing", "The stored file could not be found on the server.")
    try:
        png = render_page_png(path, page_number, settings.processing_config)
    except PdfOpenError as exc:
        raise _error(422, exc.code, exc.message) from exc
    except DocumentProcessingError as exc:
        raise _error(404, exc.code, exc.message) from exc
    except Exception as exc:
        logger.exception("Page preview failed for document %s page %d", document_id, page_number)
        raise _error(500, "internal_error", "The page could not be rendered.") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )
