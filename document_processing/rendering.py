"""Render one page as a PNG (for the source-region preview in the UI)."""

from pathlib import Path

import pymupdf

from document_processing.errors import DocumentProcessingError
from document_processing.models import ProcessingConfig
from document_processing.pdf_open import open_pdf


def render_page_png(path: Path, page_number: int, config: ProcessingConfig, max_side_px: int | None = None) -> bytes:
    """PNG of the page as a viewer shows it (rotation applied). The longest side is capped.

    Raises PdfOpenError for unreadable PDFs and DocumentProcessingError(code="page_not_found") for a bad page."""
    limit = max_side_px or config.preview_max_side_px
    doc = open_pdf(Path(path), config)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise DocumentProcessingError(f"The PDF has no page {page_number}.", code="page_not_found")
        page = doc[page_number - 1]
        longest = max(page.rect.width, page.rect.height) or 1.0
        scale = min(limit / longest, 2.5)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
