"""PdfProcessor: open a PDF, read metadata, and yield page-level extraction results.

Per-page strategy:
  1. PyMuPDF text layer.
  2. If sparse: pdfplumber text layer (different parser; sometimes recovers text PyMuPDF misses).
  3. If still sparse: render the page and OCR it with Tesseract.
     - Tesseract missing/misconfigured  -> page status `needs_ocr`, ocr_status `unavailable`, with the setup error.
     - OCR error on this page           -> page status `failed`, ocr_status `failed`.
One failing page never stops the others.
"""

import logging
from pathlib import Path
from typing import Iterator

import pymupdf

from document_processing.errors import OcrFailedError, OcrUnavailableError
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
)
from document_processing.ocr import TesseractOcr
from document_processing.pdf_open import open_pdf
from document_processing.scanned_detection import is_likely_scanned, is_text_sparse, page_has_images
from document_processing.text_extraction import (
    PdfplumberReader,
    count_text_chars,
    extract_pymupdf_text,
)

logger = logging.getLogger(__name__)

_METADATA_KEYS = ("format", "title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")
_MAX_METADATA_VALUE_LEN = 500


class PdfProcessor:
    def __init__(self, path: Path, config: ProcessingConfig | None = None, ocr: TesseractOcr | None = None) -> None:
        self._path = Path(path)
        self._config = config or ProcessingConfig()
        self._ocr = ocr or TesseractOcr(self._config)
        self._doc: pymupdf.Document | None = None
        self._plumber: PdfplumberReader | None = None
        self.page_count = 0
        self.metadata: dict[str, str] = {}

    # ---- lifecycle ----
    def __enter__(self) -> "PdfProcessor":
        self._open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._plumber is not None:
            self._plumber.close()
            self._plumber = None
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def _open(self) -> None:
        doc = open_pdf(self._path, self._config)
        self._doc = doc
        self._plumber = PdfplumberReader(self._path)
        self.page_count = doc.page_count
        self.metadata = self._read_metadata(doc)

    @staticmethod
    def _read_metadata(doc: pymupdf.Document) -> dict[str, str]:
        raw = doc.metadata or {}
        result: dict[str, str] = {}
        for key in _METADATA_KEYS:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value.replace("\x00", "").strip()[:_MAX_METADATA_VALUE_LEN]
        return result

    # ---- processing ----
    def iter_pages(self) -> Iterator[PageResult]:
        for index in range(self.page_count):
            yield self.process_page(index)

    def process_page(self, index: int) -> PageResult:
        assert self._doc is not None and self._plumber is not None, "PdfProcessor is not open"
        page_number = index + 1
        try:
            return self._process_page(index)
        except Exception as exc:  # isolate page failures
            logger.exception("Page %d failed during processing", page_number)
            return PageResult(
                page_number=page_number,
                text="",
                extraction_method=METHOD_NONE,
                char_count=0,
                has_images=False,
                is_likely_scanned=False,
                ocr_status=OCR_NOT_NEEDED,
                ocr_mean_confidence=None,
                status=PAGE_FAILED,
                error_message=f"Page could not be processed ({type(exc).__name__}).",
            )

    def _process_page(self, index: int) -> PageResult:
        cfg = self._config
        page = self._doc[index]
        text = extract_pymupdf_text(page)
        method = METHOD_PYMUPDF
        sparse = is_text_sparse(text, cfg.min_text_chars)
        has_images = page_has_images(page)
        likely_scanned = is_likely_scanned(sparse, has_images)

        if sparse:
            alt = self._plumber.extract(index)
            if count_text_chars(alt) > count_text_chars(text):
                text, method = alt, METHOD_PDFPLUMBER
                sparse = is_text_sparse(text, cfg.min_text_chars)

        ocr_status = OCR_NOT_NEEDED
        ocr_conf: float | None = None
        status = PAGE_COMPLETED
        error: str | None = None

        if sparse:
            try:
                ocr_result = self._ocr.recognize_png(self._render_png(page))
                ocr_status = OCR_COMPLETED
                ocr_conf = ocr_result.mean_confidence
                if count_text_chars(ocr_result.text) > count_text_chars(text):
                    text, method = ocr_result.text, METHOD_OCR
            except OcrUnavailableError as exc:
                ocr_status, status, error = OCR_UNAVAILABLE, PAGE_NEEDS_OCR, exc.message
            except OcrFailedError as exc:
                ocr_status, status, error = OCR_FAILED, PAGE_FAILED, exc.message

        char_count = count_text_chars(text)
        if char_count == 0:
            method = METHOD_NONE  # no text from any source (blank page, or OCR needed but not possible)

        return PageResult(
            page_number=index + 1,
            text=text,
            extraction_method=method,
            char_count=char_count,
            has_images=has_images,
            is_likely_scanned=likely_scanned,
            ocr_status=ocr_status,
            ocr_mean_confidence=ocr_conf,
            status=status,
            error_message=error,
        )

    def _render_png(self, page) -> bytes:
        cfg = self._config
        longest_pt = max(page.rect.width, page.rect.height) or 1.0
        dpi = min(cfg.ocr_dpi, 72.0 * cfg.max_ocr_image_side_px / longest_pt)
        # PyMuPDF requires an integer dpi. No lower floor: the pixel cap must always hold.
        return page.get_pixmap(dpi=max(int(dpi), 1)).tobytes("png")
