"""Clinical information extraction (Phase 5): rule- and lexicon-based extraction of lab results, vital signs,
medications, conditions, symptoms and dates from text, tables and OCR text, each tied to its exact source.

A pure-Python library: it knows nothing about FastAPI or the database. It never invents entities: every result
is a verbatim span of its source, with normalised forms stored alongside. See docs/clinical-information-extraction.md.
"""

from clinical_extraction.lexicon import lexicon_sizes
from clinical_extraction.models import (
    ASSERTIONS,
    ENTITY_TYPES,
    EXTRACTOR_VERSION,
    MODALITIES,
    Evidence,
    TableInput,
)
from clinical_extraction.pipeline import extract_table_evidence, extract_text_evidence

__all__ = [
    "ASSERTIONS", "ENTITY_TYPES", "EXTRACTOR_VERSION", "MODALITIES", "Evidence", "TableInput",
    "extract_table_evidence", "extract_text_evidence", "lexicon_sizes",
]
