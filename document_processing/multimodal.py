"""MultimodalProcessor: tables and embedded images, page by page.

Mirrors PdfProcessor: open as a context manager, then iterate pages. Tables and images on a page are
processed independently, so a failure in one never loses the other, and a failing page never stops the
document. Counters enforce the per-document limits.
"""

import logging
from pathlib import Path
from typing import Iterator

import pymupdf

from document_processing.images import extract_images
from document_processing.models import PageMultimodalResult, ProcessingConfig
from document_processing.ocr import TesseractOcr
from document_processing.pdf_open import open_pdf
from document_processing.tables import extract_tables

logger = logging.getLogger(__name__)


class MultimodalProcessor:
    def __init__(
        self,
        path: Path,
        config: ProcessingConfig | None = None,
        ocr: TesseractOcr | None = None,
        image_ocr: bool | None = None,
    ) -> None:
        self._path = Path(path)
        self._config = config or ProcessingConfig()
        self._ocr = ocr or TesseractOcr(self._config)
        self._image_ocr = self._config.image_ocr if image_ocr is None else image_ocr
        self._doc: pymupdf.Document | None = None
        self.page_count = 0
        self._tables_total = 0
        self._images_total = 0

    def __enter__(self) -> "MultimodalProcessor":
        self._doc = open_pdf(self._path, self._config)
        self.page_count = self._doc.page_count
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def iter_pages(self) -> Iterator[PageMultimodalResult]:
        for index in range(self.page_count):
            yield self.process_page(index)

    def process_page(self, index: int) -> PageMultimodalResult:
        assert self._doc is not None, "MultimodalProcessor is not open"
        cfg = self._config
        page_number = index + 1
        result = PageMultimodalResult(page_number=page_number)
        try:
            page = self._doc[index]
        except Exception as exc:
            logger.exception("Page %d could not be loaded", page_number)
            result.errors.append(f"Page could not be loaded ({type(exc).__name__}).")
            return result

        try:
            extract_tables(page, page_number, cfg, result, cfg.max_tables_per_document - self._tables_total)
        except Exception as exc:
            logger.exception("Table detection failed on page %d", page_number)
            result.tables.clear()
            result.errors.append(f"Table detection failed on this page ({type(exc).__name__}).")

        try:
            extract_images(
                self._doc, page, page_number, cfg, result,
                cfg.max_images_per_document - self._images_total, self._ocr, self._image_ocr,
            )
        except Exception as exc:
            logger.exception("Image extraction failed on page %d", page_number)
            result.images.clear()
            result.errors.append(f"Image extraction failed on this page ({type(exc).__name__}).")

        self._tables_total += len(result.tables)
        self._images_total += len(result.images)
        return result
