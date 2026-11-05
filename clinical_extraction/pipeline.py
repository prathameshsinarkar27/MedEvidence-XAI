"""Public entry points: turn page text / table / image-OCR text into scored Evidence."""

from clinical_extraction.confidence import score
from clinical_extraction.extractors import extract_from_text
from clinical_extraction.models import (
    FIELD_IMAGE_OCR,
    FIELD_PAGE_TEXT,
    MODALITY_IMAGE_OCR,
    MODALITY_OCR,
    MODALITY_TEXT,
    Evidence,
    TableInput,
)
from clinical_extraction.tables import extract_from_table


def finalize(items: list[Evidence]) -> list[Evidence]:
    for ev in items:
        ev.confidence, ev.confidence_factors = score(ev)
    return items


def extract_text_evidence(text: str, modality: str = MODALITY_TEXT, ocr_confidence: float | None = None) -> list[Evidence]:
    """Evidence from a page's text (modality text or ocr) or from an image's OCR text (modality image_ocr).
    Character offsets refer to `text`, which must be the exact string stored in the database."""
    field = FIELD_IMAGE_OCR if modality == MODALITY_IMAGE_OCR else FIELD_PAGE_TEXT
    items = extract_from_text(text)
    for ev in items:
        ev.modality, ev.source_field, ev.ocr_confidence = modality, field, ocr_confidence
    return finalize(items)


def extract_table_evidence(table: TableInput) -> tuple[list[Evidence], dict]:
    items, stats = extract_from_table(table)
    return finalize(items), stats
