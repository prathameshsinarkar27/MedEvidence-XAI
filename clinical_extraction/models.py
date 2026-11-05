"""Data types and vocabularies for clinical information extraction (Phase 5). Pure Python."""

from dataclasses import dataclass, field

EXTRACTOR_VERSION = "5.0.0"

# --- entity types ---
ENTITY_LAB_RESULT = "lab_result"
ENTITY_VITAL_SIGN = "vital_sign"
ENTITY_MEDICATION = "medication"
ENTITY_CONDITION = "condition"
ENTITY_SYMPTOM = "symptom"
ENTITY_DATE = "date"
ENTITY_TYPES = (
    ENTITY_LAB_RESULT,
    ENTITY_VITAL_SIGN,
    ENTITY_MEDICATION,
    ENTITY_CONDITION,
    ENTITY_SYMPTOM,
    ENTITY_DATE,
)

# --- modality: where the text came from ---
MODALITY_TEXT = "text"  # PDF text layer
MODALITY_OCR = "ocr"  # page OCR (scanned page)
MODALITY_TABLE = "table"  # a detected table
MODALITY_IMAGE_OCR = "image_ocr"  # OCR of text inside an embedded image
MODALITIES = (MODALITY_TEXT, MODALITY_OCR, MODALITY_TABLE, MODALITY_IMAGE_OCR)

# --- assertion: is the finding present for this patient? ---
ASSERT_AFFIRMED = "affirmed"
ASSERT_NEGATED = "negated"
ASSERT_UNCERTAIN = "uncertain"
ASSERT_FAMILY = "family_history"
ASSERT_ALLERGY = "allergy"
ASSERT_DISCONTINUED = "discontinued"
ASSERT_PLANNED = "planned"
ASSERTIONS = (
    ASSERT_AFFIRMED,
    ASSERT_NEGATED,
    ASSERT_UNCERTAIN,
    ASSERT_FAMILY,
    ASSERT_ALLERGY,
    ASSERT_DISCONTINUED,
    ASSERT_PLANNED,
)

# --- abnormal flag and where it came from ---
FLAG_HIGH = "high"
FLAG_LOW = "low"
FLAG_NORMAL = "normal"
FLAG_SOURCE_PRINTED = "printed_flag"
FLAG_SOURCE_RANGE = "printed_reference_range"

# --- text source fields (what char offsets refer to) ---
FIELD_PAGE_TEXT = "page_text"
FIELD_IMAGE_OCR = "image_ocr_text"
FIELD_TABLE_ROW = "table_row"


@dataclass
class TableInput:
    """A table handed to the extractor. `ref` is opaque to the library (the backend passes the table id)."""

    ref: object
    rows: list[list[str | None]]  # rows[r][c] = cell text; None = no cell at that position


@dataclass
class Evidence:
    """One extracted piece of clinical information, with everything needed to trace it to its source.

    The mention (`mention_text`) and its sentence/row (`source_text`) are copied verbatim from the source;
    nothing here is generated. Normalised fields (`entity_name`, `unit_normalized`, `date_iso`, ...) are
    derived by fixed rules and always sit beside the original text.
    """

    entity_type: str
    entity_name: str  # canonical name from the lexicon ("Hemoglobin A1c"); role/"date" for dates
    mention_text: str  # exact text matched in the source
    source_text: str  # exact sentence / line / table row containing the mention
    modality: str
    extraction_method: str  # e.g. "rule_measurement_inline_v1"
    source_field: str = FIELD_PAGE_TEXT
    char_start: int | None = None  # mention span in the source field text
    char_end: int | None = None
    source_start: int | None = None  # source_text span in the source field text
    source_end: int | None = None
    assertion: str = ASSERT_AFFIRMED
    value_text: str | None = None  # as written ("7.8", "140/90", "500 mg")
    value_numeric: float | None = None
    value_comparator: str | None = None  # "<", ">", "<=", ">="
    unit_text: str | None = None  # as written
    unit_normalized: str | None = None  # canonical spelling only; values are never converted
    reference_text: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    abnormal_flag: str | None = None
    flag_source: str | None = None
    date_text: str | None = None
    date_iso: str | None = None
    attributes: dict = field(default_factory=dict)
    # table provenance (opaque ref + positions of the cells the evidence was read from)
    table_ref: object | None = None
    row_index: int | None = None
    cell_positions: list[tuple[int, int]] = field(default_factory=list)
    confidence: float = 0.0
    confidence_factors: dict = field(default_factory=dict)
    # filled by the caller (page/image context)
    ocr_confidence: float | None = None
