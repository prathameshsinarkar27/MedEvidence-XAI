import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProcessAccepted(BaseModel):
    document_id: uuid.UUID
    processing_status: str


class ProcessingStatusOut(BaseModel):
    document_id: uuid.UUID
    processing_status: str  # not_processed | queued | processing | completed | completed_with_errors | failed
    page_count: int | None
    pages_processed: int  # pages already stored (progress while running)
    pages_by_method: dict[str, int]  # pymupdf | pdfplumber | ocr_tesseract | none
    pages_by_status: dict[str, int]  # completed | needs_ocr | failed
    pages_by_ocr_status: dict[str, int]  # not_needed | completed | unavailable | failed
    likely_scanned_pages: int
    error_code: str | None
    error_message: str | None
    processed_at: datetime | None


class PageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID  # page_id
    document_id: uuid.UUID
    page_number: int
    extraction_method: str
    char_count: int
    processing_status: str
    ocr_status: str
    ocr_mean_confidence: float | None
    has_images: bool
    is_likely_scanned: bool
    error_message: str | None


class PageDetail(PageSummary):
    extracted_text: str


class PageList(BaseModel):
    document_id: uuid.UUID
    page_count: int | None
    items: list[PageSummary]


class TesseractCapability(BaseModel):
    available: bool
    version: str | None
    requested_languages: list[str]
    installed_languages: list[str]
    missing_languages: list[str]
    message: str | None  # setup instructions when not available


class MultimodalCapability(BaseModel):
    table_engine: str
    auto_multimodal: bool  # tables/images are extracted automatically after text processing
    image_ocr_default: bool  # OCR of text inside images is on by default (IMAGE_OCR)
    min_image_side_px: int
    max_images_per_document: int
    max_tables_per_document: int
    max_image_bytes: int


class Capabilities(BaseModel):
    pdf_engine: str
    ocr: TesseractCapability
    min_text_chars_per_page: int
    ocr_dpi: int
    max_pdf_pages: int
    multimodal: MultimodalCapability | None = None  # Phase 4
