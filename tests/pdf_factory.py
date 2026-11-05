"""Builds small SYNTHETIC PDFs for tests and sample data. No real patient information.

Every function returns PDF bytes. "Scanned" PDFs are produced by rendering text to an image and
placing only that image on the page, so the result has no text layer (like a real scan).
"""

import io
from typing import Sequence

import pymupdf
from PIL import Image, ImageDraw

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


# ===================== Phase 4: tables and images (all content invented) =====================

LAB_TABLE_ROWS: list[list[str]] = [
    ["Test", "Result", "Unit", "Reference"],
    ["Hemoglobin A1c", "7.8", "%", "4.0 - 5.6"],
    ["Fasting glucose", "110", "mg/dL", "70 - 99"],
    ["Sodium", "140", "mmol/L", "135 - 145"],
]
_COL_WIDTHS = [130, 70, 80, 100]


def draw_ruled_table(page, rows=LAB_TABLE_ROWS, *, x0: float = 72, y0: float = 120, row_height: float = 24,
                     col_widths: Sequence[float] = _COL_WIDTHS) -> pymupdf.Rect:
    """Table with drawn cell borders. Returns the table's outer rectangle."""
    for r, row in enumerate(rows):
        x = x0
        for c, text in enumerate(row):
            cell = pymupdf.Rect(x, y0 + r * row_height, x + col_widths[c], y0 + (r + 1) * row_height)
            page.draw_rect(cell, width=0.8)
            if text:
                page.insert_text((cell.x0 + 5, cell.y1 - 8), text, fontsize=11)
            x += col_widths[c]
    return pymupdf.Rect(x0, y0, x0 + sum(col_widths[: len(rows[0])]), y0 + len(rows) * row_height)


def draw_borderless_table(page, rows=LAB_TABLE_ROWS, *, x0: float = 72, y0: float = 420, row_height: float = 20,
                          col_widths: Sequence[float] = _COL_WIDTHS) -> None:
    """Aligned columns of text with no lines at all."""
    for r, row in enumerate(rows):
        x = x0
        for c, text in enumerate(row):
            page.insert_text((x, y0 + r * row_height), text, fontsize=11)
            x += col_widths[c]


def bar_chart_png(width: int = 240, height: int = 140) -> bytes:
    """A synthetic bar-chart-like picture (no text), the kind of figure found in reports."""
    image = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for i, bar in enumerate([40, 75, 55, 100, 85]):
        x = 20 + i * 40
        draw.rectangle([x, height - 10 - bar, x + 28, height - 10], fill=(40 + i * 30, 90, 160))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def jpeg_bytes(width: int = 120, height: int = 90, mode: str = "RGB") -> bytes:
    colour = (200, 120, 40, 0) if mode == "CMYK" else (200, 120, 40)
    image = Image.new(mode, (width, height), colour)
    ImageDraw.Draw(image).ellipse([10, 10, width - 10, height - 10], outline=(10, 10, 10, 0) if mode == "CMYK" else (10, 10, 10))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def text_image_png(lines: Lines, fontsize: float = 22, width: float = 420) -> bytes:
    """A picture of printed text (like a screenshot or a figure with a printed label)."""
    source = pymupdf.open()
    page = source.new_page(width=width, height=40 + len(lines) * fontsize * 1.6)
    _write_lines(page, lines, fontsize, top=fontsize + 12)
    return page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY).tobytes("png")


def table_pdf(rows=LAB_TABLE_ROWS, *, ruled: bool = True, rotation: int = 0, caption: str = "Synthetic lab results table") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), caption, fontsize=14)
    if ruled:
        draw_ruled_table(page, rows, y0=120)
    else:
        draw_borderless_table(page, rows, y0=130)
    if rotation:
        page.set_rotation(rotation)
    return doc.tobytes(deflate=True, garbage=3)


def image_pdf(placements: Sequence[tuple[bytes, tuple[float, float, float, float]]], *, rotation: int = 0,
              page_size: tuple[float, float] = (595, 842)) -> bytes:
    """One page with the given (image bytes, (x0, y0, x1, y1)) placements."""
    doc = pymupdf.open()
    page = doc.new_page(width=page_size[0], height=page_size[1])
    for data, rect in placements:
        page.insert_image(pymupdf.Rect(*rect), stream=data)
    if rotation:
        page.set_rotation(rotation)
    return doc.tobytes(deflate=True, garbage=3)


def multimodal_pdf() -> bytes:
    """Sample report: page 1 has a ruled table, a borderless table and a figure; page 2 is prose only."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "SYNTHETIC MULTIMODAL REPORT - NOT A REAL PATIENT", fontsize=14)
    draw_ruled_table(page, LAB_TABLE_ROWS, y0=110)
    page.insert_text((72, 240), "Figure 1: synthetic bar chart (illustration only)", fontsize=11)
    page.insert_image(pymupdf.Rect(72, 250, 312, 390), stream=bar_chart_png())
    page.insert_text((72, 420), "Medication schedule (synthetic)", fontsize=11)
    draw_borderless_table(
        page,
        [["Drug", "Dose", "Frequency"], ["Metformin", "500 mg", "twice daily"], ["Amlodipine", "5 mg", "once daily"],
         ["Atorvastatin", "20 mg", "at night"]],
        y0=440,
        col_widths=[130, 90, 120],
    )
    page.insert_image(pymupdf.Rect(340, 250, 520, 330), stream=text_image_png(["Chart legend", "Series A: 7.8 %"], fontsize=18, width=300))
    second = doc.new_page()
    for i, line in enumerate(
        ["Page two contains prose only: the patient was seen in clinic and the plan was reviewed.",
         "No tables or figures appear on this page (synthetic text)."]
    ):
        second.insert_text((72, 100 + i * 20), line, fontsize=11)
    return doc.tobytes(deflate=True, garbage=3)


# ===================== Phase 5: clinical information (all content invented) =====================

CLINICAL_NOTE_LINES: list[str] = [
    "SYNTHETIC CLINIC NOTE - NOT A REAL PATIENT",
    "Visit date: 12-Aug-2026",
    "Patient denies chest pain or fever. History of type 2 diabetes mellitus.",
    "Possible peripheral neuropathy. Mother had hypertension. Allergic to penicillin.",
    "Current medication: Metformin 500 mg twice daily PO; amlodipine 5 mg once daily.",
    "Aspirin was discontinued last month. Vitals: BP 140/90 mmHg, heart rate 78 bpm.",
    "HbA1c was 7.8 % on 12-Aug-2026. Follow-up planned for 03/09/2026.",
]


def clinical_note_pdf() -> bytes:
    """One page: narrative note (negation, uncertainty, family history, allergy, medications, vitals, dates)
    followed by a ruled lab table."""
    doc = pymupdf.open()
    page = doc.new_page()
    _write_lines(page, CLINICAL_NOTE_LINES, 9, top=80, step=16)
    page.insert_text((72, 220), "Laboratory results (synthetic)", fontsize=10)
    draw_ruled_table(page, LAB_TABLE_ROWS, y0=235)
    return doc.tobytes(deflate=True, garbage=3)
