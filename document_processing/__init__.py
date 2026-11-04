"""PDF text extraction and OCR (Phase 3), tables and embedded images (Phase 4).

A pure-Python library: it knows nothing about FastAPI or the database. The backend calls
`PdfProcessor` and persists the `PageResult`s it yields.

Out of scope: interpreting image content (no medical-image analysis), clinical extraction.
"""

from document_processing.errors import (
    DocumentProcessingError,
    OcrFailedError,
    OcrUnavailableError,
    PdfOpenError,
)
from document_processing.geometry import display_box, display_region, display_size
from document_processing.models import (
    IMAGE_EXTRACTED,
    IMAGE_FAILED,
    IMG_OCR_COMPLETED,
    IMG_OCR_FAILED,
    IMG_OCR_NO_TEXT,
    IMG_OCR_NOT_REQUESTED,
    IMG_OCR_SKIPPED_PAGE_SCAN,
    IMG_OCR_UNAVAILABLE,
    MM_PAGE_COMPLETED,
    MM_PAGE_FAILED,
    TABLE_METHOD_PYMUPDF,
    ImageResult,
    PageMultimodalResult,
    TableCellResult,
    TableResult,
    METHOD_NONE,
    METHOD_OCR,
    METHOD_PDFPLUMBER,
    METHOD_PYMUPDF,
    OCR_COMPLETED,
    OCR_FAILED,
    OCR_NOT_NEEDED,
    OCR_UNAVAILABLE,
    PAGE_COMPLETED,
    PAGE_FAILED,
    PAGE_NEEDS_OCR,
    PageResult,
    ProcessingConfig,
    TesseractStatus,
)
from document_processing.ocr import TesseractOcr, check_tesseract
from document_processing.multimodal import MultimodalProcessor
from document_processing.pdf_processor import PdfProcessor
from document_processing.rendering import render_page_png

__all__ = [
    "IMAGE_EXTRACTED",
    "IMAGE_FAILED",
    "IMG_OCR_COMPLETED",
    "IMG_OCR_FAILED",
    "IMG_OCR_NO_TEXT",
    "IMG_OCR_NOT_REQUESTED",
    "IMG_OCR_SKIPPED_PAGE_SCAN",
    "IMG_OCR_UNAVAILABLE",
    "MM_PAGE_COMPLETED",
    "MM_PAGE_FAILED",
    "TABLE_METHOD_PYMUPDF",
    "ImageResult",
    "PageMultimodalResult",
    "TableCellResult",
    "TableResult",
    "MultimodalProcessor",
    "render_page_png",
    "display_box",
    "display_region",
    "display_size",

    "DocumentProcessingError",
    "OcrFailedError",
    "OcrUnavailableError",
    "PdfOpenError",
    "METHOD_NONE",
    "METHOD_OCR",
    "METHOD_PDFPLUMBER",
    "METHOD_PYMUPDF",
    "OCR_COMPLETED",
    "OCR_FAILED",
    "OCR_NOT_NEEDED",
    "OCR_UNAVAILABLE",
    "PAGE_COMPLETED",
    "PAGE_FAILED",
    "PAGE_NEEDS_OCR",
    "PageResult",
    "PdfProcessor",
    "ProcessingConfig",
    "TesseractOcr",
    "TesseractStatus",
    "check_tesseract",
]
