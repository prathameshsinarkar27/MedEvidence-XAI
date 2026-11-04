"""Text-layer extraction with PyMuPDF (primary) and pdfplumber (secondary fallback)."""

import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


def clean_text(text: str | None) -> str:
    """Remove NUL characters (PostgreSQL text columns reject them). Nothing else is altered."""
    return (text or "").replace("\x00", "")


def count_text_chars(text: str) -> int:
    """Number of non-whitespace characters."""
    return sum(1 for ch in text if not ch.isspace())


def extract_pymupdf_text(page) -> str:
    # sort=False keeps the PDF's own content order; layout reconstruction is out of scope.
    return clean_text(page.get_text("text"))


class PdfplumberReader:
    """Opens the file once with pdfplumber; every failure degrades to an empty string."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._pdf = None
        self._failed = False

    def _open(self):
        if self._pdf is None and not self._failed:
            try:
                self._pdf = pdfplumber.open(self._path)
            except Exception as exc:  # pdfminer raises many exception types
                logger.debug("pdfplumber could not open the file: %s", type(exc).__name__)
                self._failed = True
        return self._pdf

    def extract(self, page_index: int) -> str:
        pdf = self._open()
        if pdf is None:
            return ""
        try:
            return clean_text(pdf.pages[page_index].extract_text())
        except Exception as exc:
            logger.debug("pdfplumber failed on page index %d: %s", page_index, type(exc).__name__)
            return ""

    def close(self) -> None:
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._pdf = None
