"""PDF processing endpoints: start, status, page content, system capabilities."""

import uuid

import pymupdf
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_session, get_session_factory
from app.models.document import Document
from app.schemas.processing import (
    Capabilities,
    ClinicalCapability,
    PageDetail,
    PageList,
    PageSummary,
    ProcessAccepted,
    ProcessingStatusOut,
    MultimodalCapability,
    TesseractCapability,
)
from app.services import documents as document_service
from app.services import multimodal as multimodal_service
from app.services import processing as processing_service
from clinical_extraction import ASSERTIONS, ENTITY_TYPES, EXTRACTOR_VERSION, lexicon_sizes
from document_processing import check_tesseract

documents_router = APIRouter(prefix="/documents", tags=["processing"])
system_router = APIRouter(prefix="/processing", tags=["processing"])


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def _require_document(session: Session, document_id: uuid.UUID) -> Document:
    document = document_service.get_document(session, document_id)
    if document is None:
        raise _not_found("document_not_found", "Document not found.")
    return document


@documents_router.post(
    "/{document_id}/process",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or restart) text extraction + OCR (then tables and images, if AUTO_MULTIMODAL is on)",
)
def start_processing(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    session_factory: sessionmaker = Depends(get_session_factory),
) -> ProcessAccepted:
    _require_document(session, document_id)
    if not processing_service.claim_for_processing(session, document_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "processing_in_progress", "message": "This document is already being processed."},
        )
    background_tasks.add_task(multimodal_service.run_pipeline, session_factory, get_settings(), document_id)
    return ProcessAccepted(document_id=document_id, processing_status="queued")


@documents_router.get(
    "/{document_id}/processing", response_model=ProcessingStatusOut, summary="Processing status and progress"
)
def get_processing_status(document_id: uuid.UUID, session: Session = Depends(get_session)) -> ProcessingStatusOut:
    document = _require_document(session, document_id)
    return processing_service.build_status(session, document)


@documents_router.get("/{document_id}/pages", response_model=PageList, summary="Page summaries (no text)")
def list_pages(document_id: uuid.UUID, session: Session = Depends(get_session)) -> PageList:
    document = _require_document(session, document_id)
    pages = processing_service.list_pages(session, document_id)
    return PageList(
        document_id=document_id,
        page_count=document.page_count,
        items=[PageSummary.model_validate(p) for p in pages],
    )


@documents_router.get(
    "/{document_id}/pages/{page_number}", response_model=PageDetail, summary="Extracted text of one page"
)
def get_page(
    document_id: uuid.UUID,
    page_number: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> PageDetail:
    _require_document(session, document_id)
    page = processing_service.get_page(session, document_id, page_number)
    if page is None:
        raise _not_found("page_not_found", "Page not found (it may not have been processed yet).")
    return PageDetail.model_validate(page)


@system_router.get("/capabilities", response_model=Capabilities, summary="Extraction engine and OCR availability")
def capabilities() -> Capabilities:
    settings = get_settings()
    tesseract = check_tesseract(settings.processing_config)
    return Capabilities(
        pdf_engine=f"PyMuPDF {pymupdf.__version__}",
        ocr=TesseractCapability(
            available=tesseract.available,
            version=tesseract.version,
            requested_languages=tesseract.requested_languages,
            installed_languages=tesseract.installed_languages,
            missing_languages=tesseract.missing_languages,
            message=tesseract.message,
        ),
        min_text_chars_per_page=settings.min_text_chars_per_page,
        ocr_dpi=settings.ocr_dpi,
        max_pdf_pages=settings.max_pdf_pages,
        multimodal=MultimodalCapability(
            table_engine=f"PyMuPDF {pymupdf.__version__} Page.find_tables",
            auto_multimodal=settings.auto_multimodal,
            image_ocr_default=settings.image_ocr,
            min_image_side_px=settings.min_image_side_px,
            max_images_per_document=settings.max_images_per_document,
            max_tables_per_document=settings.max_tables_per_document,
            max_image_bytes=settings.max_image_bytes,
        ),
        clinical=ClinicalCapability(
            extractor_version=EXTRACTOR_VERSION,
            approach="Rule-based and lexicon-based extraction (regular expressions, small built-in vocabularies, "
            "NegEx-style negation rules). No trained model.",
            auto_clinical_extraction=settings.auto_clinical_extraction,
            max_evidence_per_document=settings.max_evidence_per_document,
            lexicon_sizes=lexicon_sizes(),
            entity_types=list(ENTITY_TYPES),
            assertions=list(ASSERTIONS),
        ),
    )
