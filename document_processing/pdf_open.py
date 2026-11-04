"""Shared PDF opening with the same safety checks for every pipeline stage."""

from pathlib import Path

import pymupdf

from document_processing.errors import PdfOpenError
from document_processing.models import ProcessingConfig


def open_pdf(path: Path, config: ProcessingConfig) -> pymupdf.Document:
    """Open a PDF read-only. Raises PdfOpenError (corrupt, encrypted, empty, too many pages)."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfOpenError("The file could not be opened as a PDF (it may be corrupt or truncated).") from exc
    if doc.needs_pass:
        doc.close()
        raise PdfOpenError("The PDF is password-protected; encrypted PDFs are not supported.", code="encrypted_pdf")
    if doc.page_count == 0:
        doc.close()
        raise PdfOpenError("The PDF contains no pages.", code="empty_pdf")
    if doc.page_count > config.max_pages:
        count = doc.page_count
        doc.close()
        raise PdfOpenError(
            f"The PDF has {count} pages; the limit is {config.max_pages} (MAX_PDF_PAGES).",
            code="too_many_pages",
        )
    return doc
