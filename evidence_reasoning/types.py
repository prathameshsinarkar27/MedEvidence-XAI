"""Data types and configuration for question understanding and evidence verification (Phase 8). Pure Python."""

from dataclasses import dataclass, field

# --- question types (a question can have several; `primary` is the most specific one) ---
Q_COMPARISON = "comparison"
Q_RELATIONSHIP = "relationship"
Q_SUMMARY = "summary"
Q_VALUE = "value_lookup"
Q_TEMPORAL = "temporal"
Q_ENTITY = "entity_focused"
Q_UNCLASSIFIED = "unclassified"
QUESTION_TYPES = (Q_COMPARISON, Q_RELATIONSHIP, Q_SUMMARY, Q_VALUE, Q_TEMPORAL, Q_ENTITY)  # precedence order

# --- evidence states ---
SUPPORTED = "supported"
PARTIAL = "partially_supported"
CONFLICTING = "conflicting"
INSUFFICIENT = "insufficient_evidence"
STATES = (SUPPORTED, PARTIAL, CONFLICTING, INSUFFICIENT)

# --- conflict categories ---
TEMPORAL_CHANGE = "temporal_change"
MEASUREMENT_VARIATION = "measurement_variation"
POSSIBLE_CONTRADICTION = "possible_contradiction"
CONFLICT_CATEGORIES = (TEMPORAL_CHANGE, MEASUREMENT_VARIATION, POSSIBLE_CONTRADICTION)

VALUED_TYPES = ("lab_result", "vital_sign", "medication")


@dataclass(frozen=True)
class ValueConstraint:
    """A number the question states, e.g. 'above 7 %' (comparator '>') or 'HbA1c 7.8' (comparator '=')."""
    comparator: str  # = > >= < <=
    value: float
    unit: str | None = None  # canonical unit when recognised
    value2: float | None = None  # diastolic of a blood-pressure pair
    text: str = ""


@dataclass
class QuestionAnalysis:
    text: str
    types: list[str]
    primary: str
    cues: dict[str, list[str]]  # type -> the words that triggered it (transparency)
    entities: list[str]  # canonical names
    entity_types: dict[str, str]  # canonical name -> lab_result | vital_sign | medication | condition | symptom
    entity_mentions: list[str]
    periods: list[tuple[str, str]]  # inclusive ISO ranges (ambiguous dates keep both readings)
    recency: str | None  # latest | earliest
    page_hint: int | None
    value_constraints: list[ValueConstraint]
    requested: list[str]  # value | date | presence | list | change | relationship
    requested_entity_types: list[str]
    assertion_focus: str | None  # family_history | allergy | discontinued | planned
    yes_no: bool
    advice_request: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VEvidence:
    """What verification needs to know about one retrieved evidence item (no database objects)."""
    id: str
    document_id: str
    document_filename: str
    page_number: int
    entity_type: str
    entity_name: str
    assertion: str
    modality: str
    extraction_confidence: float
    source_text: str = ""
    source_start: int | None = None
    source_end: int | None = None
    value_text: str | None = None
    value_numeric: float | None = None
    value_comparator: str | None = None
    unit_normalized: str | None = None
    date_iso: str | None = None
    ocr_confidence: float | None = None
    attributes: dict = field(default_factory=dict)
    retrieval_rank: int = 0
    semantic: float | None = None  # Phase 7 semantic component (None = unavailable)
    order: tuple = ()  # deterministic tie-break


VERIFY_COMPONENTS = ("relevance", "entity", "value", "temporal", "confidence", "source", "directness", "agreement")
VERIFY_FORMULA = ("evidence_score = sum(w_c * c) / sum(w_c), over the components c that apply to this evidence and question; "
                  "components: " + ", ".join(VERIFY_COMPONENTS))


@dataclass(frozen=True)
class VerifyWeights:
    """Engineering defaults chosen by reasoning (what should matter most), NOT tuned on data: Not yet evaluated."""
    relevance: float = 1.0
    entity: float = 1.5
    value: float = 0.5
    temporal: float = 1.0
    confidence: float = 0.75
    source: float = 0.75
    directness: float = 2.0
    agreement: float = 0.5

    def __post_init__(self) -> None:
        for name in VERIFY_COMPONENTS:
            if getattr(self, name) < 0:
                raise ValueError(f"weight {name} must be >= 0")

    def as_dict(self) -> dict[str, float]:
        return {c: getattr(self, c) for c in VERIFY_COMPONENTS}


@dataclass(frozen=True)
class ReasoningConfig:
    weights: VerifyWeights = field(default_factory=VerifyWeights)
    supported_score: float = 0.70  # evidence_score needed for an item to count as supporting
    min_relevant_score: float = 0.35  # below this an item is excluded from the analysis
    min_semantic_no_entity: float = 0.30  # without a recognised entity only semantic similarity links evidence to the question
    undated_temporal_score: float = 0.25  # temporal consistency of undated evidence when the question has a time constraint
    # Largest relative difference still called "measurement variation" for values with the same (or unknown) time.
    # Uncalibrated engineering defaults, not clinical thresholds.
    tolerance_lab: float = 0.05
    tolerance_vital: float = 0.10
    tolerance_medication: float = 0.0
    tolerance_default: float = 0.05

    def tolerance(self, entity_type: str) -> float:
        return {"lab_result": self.tolerance_lab, "vital_sign": self.tolerance_vital,
                "medication": self.tolerance_medication}.get(entity_type, self.tolerance_default)


@dataclass
class ConflictPair:
    evidence_ids: tuple[str, str]
    entity_name: str
    category: str
    reason: str  # machine code
    explanation: str
    strength: str  # moderate | weak (weak: the time of one value is unknown)
    details: dict = field(default_factory=dict)
    in_scope: bool = True  # both items satisfy the question's constraints


@dataclass
class ConflictAnalysis:
    pairs: list[ConflictPair]
    timelines: dict[str, list[dict]]  # entity -> dated values in time order (>= 2 dated points)
    counts: dict[str, int]
    skipped: list[dict]  # pairs that could not be compared (e.g. different units), with the reason
    agreements: dict[str, list[str]]  # evidence id -> ids of items stating the same finding


@dataclass
class ItemVerification:
    id: str
    score: float
    terms: dict[str, dict]  # component -> {score|None, weight, contribution|None, note}
    directness: str  # direct | indirect | not_relevant
    directness_reasons: list[str]
    constraints: dict[str, str]  # period | page | recency -> met | unmet | unknown | n/a
    in_scope: bool
    role: str  # supporting | context | excluded
    assertion_note: str | None
    corroborating_ids: list[str]
    conflict_ids: list[str]
    claim_check: str | None = None  # confirms | contradicts | undetermined (only when the question states a value)


@dataclass
class Reason:
    code: str
    text: str
    kind: str  # decisive | limiting | info


@dataclass
class EvidenceState:
    state: str
    reasons: list[Reason]
    supporting_ids: list[str]
    context_ids: list[str]
    conflicting_ids: list[str]
    coverage: dict[str, str]  # target (entity / type) -> covered | partial | missing
    claim_assessment: str | None = None


@dataclass
class VerificationResult:
    items: list[ItemVerification]
    conflicts: ConflictAnalysis
    state: EvidenceState
