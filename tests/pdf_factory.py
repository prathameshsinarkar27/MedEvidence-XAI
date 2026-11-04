"""Builds small SYNTHETIC PDFs for tests and sample data. No real patient information.

Every function returns PDF bytes. "Scanned" PDFs are produced by rendering text to an image and
placing only that image on the page, so the result has no text layer (like a real scan).
"""

from typing import Sequence

import pymupdf

Lines = Sequence[str]


def _write_lines(page, lines: Lines, fontsize: float, top: float = 100, step: float | None = None) -> None:
    step = step or fontsize * 1.8
    for i, line in enumerate(lines):
        page.insert_text((72, top + i * step), line, fontsize=fontsize)


def text_pdf(pages: Sequence[Lines], *, title: str | None = None, fontsize: float = 14) -> bytes:
    doc = pymupdf.open()
    for lines in pages:
        _write_lines(doc.new_page(), lines, fontsize)
    if title:
        doc.set_metadata({"title": title, "author": "Synthetic Generator"})
    return doc.tobytes(deflate=True, garbage=3)


def _scanned_page_png(lines: Lines, fontsize: float, dpi: int) -> bytes:
    source = pymupdf.open()
    page = source.new_page()
    _write_lines(page, lines, fontsize)
    return page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")  # grayscale keeps files small


def scanned_pdf(pages: Sequence[Lines], *, fontsize: float = 28, dpi: int = 150) -> bytes:
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        page.insert_image(page.rect, stream=_scanned_page_png(lines, fontsize, dpi))
    return doc.tobytes(deflate=True, garbage=3)


def mixed_pdf(text_lines: Lines, scanned_lines: Lines, *, scanned_fontsize: float = 28) -> bytes:
    """Page 1 has a text layer; page 2 is image-only."""
    doc = pymupdf.open()
    _write_lines(doc.new_page(), text_lines, 14)
    page = doc.new_page()
    page.insert_image(page.rect, stream=_scanned_page_png(scanned_lines, scanned_fontsize, 150))
    return doc.tobytes(deflate=True, garbage=3)


def blank_pdf(page_count: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(page_count):
        doc.new_page()
    return doc.tobytes(deflate=True, garbage=3)


def encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    _write_lines(doc.new_page(), ["Synthetic encrypted document"], 14)
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pw", user_pw="user-pw")


def large_page_pdf(width: float = 10000, height: float = 6000) -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=width, height=height)
    return doc.tobytes(deflate=True, garbage=3)


# Content used by several tests and by scripts/generate_sample_pdfs.py (all values are invented).
LAB_REPORT_LINES: list[str] = [
    "SYNTHETIC LABORATORY REPORT - NOT A REAL PATIENT",
    "Patient: Synthetic Patient A    Report date: 12-Aug-2026",
    "Test                 Result     Unit     Reference",
    "Hemoglobin A1c       7.8        %        4.0 - 5.6",
    "Fasting glucose      110        mg/dL    70 - 99",
]
