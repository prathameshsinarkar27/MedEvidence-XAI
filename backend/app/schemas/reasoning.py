"""Response models for question understanding, evidence verification and conflict analysis (Phase 8)."""

from pydantic import BaseModel

from app.schemas.evidence_index import EvidenceRecord
from app.schemas.hybrid import ComponentScore, QueryAnalysisOut


class ValueConstraintOut(BaseModel):
    comparator: str
    value: float
    unit: str | None
    value2: float | None
    text: str


class QuestionUnderstandingOut(BaseModel):
    text: str
    types: list[str]  # comparison | relationship | summary | value_lookup | temporal | entity_focused | unclassified
    primary: str
    cues: dict[str, list[str]]  # the words that triggered each type
    entities: list[str]
    entity_types: dict[str, str]
    entity_mentions: list[str]
    periods: list[tuple[str, str]]
    recency: str | None
    page_hint: int | None
    value_constraints: list[ValueConstraintOut]
    requested: list[str]  # value | date | presence | list | change | relationship
    requested_entity_types: list[str]
    assertion_focus: str | None
    yes_no: bool
    advice_request: bool
    notes: list[str]


class VerificationTerm(BaseModel):
    score: float | None  # None = the component does not apply to this evidence/question
    weight: float
    contribution: float | None  # weight * score / sum of applicable weights
    note: str


class ItemVerificationOut(BaseModel):
    score: float  # evidence_score: ordering and gating only; not a probability
    verification_rank: int
    terms: dict[str, VerificationTerm]
    directness: str  # direct | indirect | not_relevant
    directness_reasons: list[str]
    constraints: dict[str, str]  # period | page | recency -> met | unmet | unknown | n/a
    in_scope: bool
    role: str  # supporting | context | excluded
    assertion_note: str | None
    corroborating_ids: list[str]
    conflict_ids: list[str]
    claim_check: str | None  # confirms | contradicts | undetermined, when the question states a value


class VerifiedHit(BaseModel):
    retrieval_rank: int
    retrieval_score: float
    retrieval_components: dict[str, ComponentScore]
    matched_terms: list[str]
    temporal_note: str | None
    evidence: EvidenceRecord
    verification: ItemVerificationOut


class ConflictPairOut(BaseModel):
    evidence_ids: list[str]
    entity_name: str
    category: str  # temporal_change | measurement_variation | possible_contradiction
    reason: str
    explanation: str
    strength: str  # moderate | weak
    details: dict
    in_scope: bool


class ConflictAnalysisOut(BaseModel):
    pairs: list[ConflictPairOut]
    timelines: dict[str, list[dict]]
    counts: dict[str, int]
    skipped: list[dict]


class ReasonOut(BaseModel):
    code: str
    text: str
    kind: str  # decisive | limiting | info


class EvidenceStateOut(BaseModel):
    state: str  # supported | partially_supported | conflicting | insufficient_evidence
    reasons: list[ReasonOut]
    supporting_evidence_ids: list[str]
    context_evidence_ids: list[str]
    conflicting_evidence_ids: list[str]
    coverage: dict[str, str]  # question target -> covered | partial | missing
    claim_assessment: str | None


class RetrievalSummary(BaseModel):
    mode: str
    pool_size: int
    candidates: int
    returned: int
    formula: str
    weights: dict[str, float]
    analysis: QueryAnalysisOut
    filters: dict
    semantic_available: bool
    embedding_model: str | None
    is_semantic: bool
    warnings: list[str]


class VerificationResponse(BaseModel):
    """Question -> retrieved evidence -> ranked evidence -> verification -> conflict analysis -> evidence state."""
    question: str
    understanding: QuestionUnderstandingOut
    retrieval: RetrievalSummary
    ranked_evidence: list[VerifiedHit]
    conflict_analysis: ConflictAnalysisOut
    evidence_state: EvidenceStateOut
    note: str


class ReasoningConfigOut(BaseModel):
    verification_formula: str
    weights: dict[str, float]
    component_descriptions: dict[str, str]
    thresholds: dict[str, float]
    conflict_tolerances: dict[str, float]
    question_types: list[str]
    evidence_states: list[str]
    conflict_categories: list[str]
    candidates: int
    note: str
