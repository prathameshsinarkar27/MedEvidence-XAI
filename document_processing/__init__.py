"""PDF text extraction and OCR (Phase 3).

A pure-Python library: it knows nothing about FastAPI or the database. The backend calls
`PdfProcessor` and persists the `PageResult`s it yields.

Out of scope for this phase: tables, embedded-image understanding, clinical extraction.
"""

from document_processing.errors import (
    DocumentProcessingError,
    OcrFailedError,
    OcrUnavailableError,
    PdfOpenError,
)
from document_processing.models import (
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
from document_processing.pdf_processor import PdfProcessor

__all__ = [
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
