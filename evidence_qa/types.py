"""Data types for evidence-grounded answer generation (Phase 9). Pure Python: no database, web or model imports."""

from dataclasses import dataclass, field

ABSTENTION_MESSAGE = "The uploaded documents do not contain sufficient evidence to answer this question."
DISCLAIMER = ("This is a research/educational prototype and is not a substitute for professional medical diagnosis or treatment. "
              "It reports what the uploaded documents state; it gives no diagnosis and no treatment recommendation.")

# answer statuses
ANSWERED = "answered"
ANSWERED_WITH_CAVEATS = "answered_with_caveats"
CONFLICT_REPORTED = "conflict_reported"
ABSTAINED = "abstained"
STATUSES = (ANSWERED, ANSWERED_WITH_CAVEATS, CONFLICT_REPORTED, ABSTAINED)

# claim kinds
FACT, CHANGE, CHECK, CONFLICT, CO_MENTION, CONTEXT = "fact", "change", "check", "conflict", "co_mention", "context"


@dataclass(frozen=True)
class CtxEvidence:
    """One verified evidence item as the answer generator sees it."""
    id: str
    entity_name: str
    entity_type: str
    assertion: str
    document_filename: str
    page_number: int
    source_text: str
    mention_text: str = ""
    value_text: str | None = None
    value_comparator: str | None = None
    unit_text: str | None = None
    date_iso: str | None = None
    date_text: str | None = None
    modality: str = "text"
    extraction_confidence: float = 0.0
    ocr_confidence: float | None = None
    evidence_score: float = 0.0  # Phase 8 verification score
    role: str = "supporting"  # supporting | context | excluded
    claim_check: str | None = None  # confirms | contradicts | undetermined
    selection: dict = field(default_factory=dict)  # facts for the explanation (rank, terms, constraints, directness ...)


@dataclass(frozen=True)
class CtxConflict:
    evidence_ids: tuple[str, str]
    entity_name: str
    category: str  # temporal_change | measurement_variation | possible_contradiction
    strength: str
    in_scope: bool
    direction: str | None = None  # increased | decreased | unchanged (temporal change of values)


@dataclass
class AnswerContext:
    """The verified evidence context. The answer generator receives ONLY this: nothing else about the documents."""
    question: str
    primary_type: str
    requested: list[str]
    entities: list[str]
    recency: str | None
    periods: list[tuple[str, str]]
    state: str  # supported | partially_supported | conflicting | insufficient_evidence
    state_reasons: list[tuple[str, str, str]]  # (code, text, kind)
    advice_request: bool
    supporting: list[CtxEvidence]
    context: list[CtxEvidence]
    conflicting_ids: list[str]
    conflicts: list[CtxConflict]
    claim_assessment: str | None = None
    value_constraint_texts: list[str] = field(default_factory=list)
    coverage: dict[str, str] = field(default_factory=dict)

    def by_id(self) -> dict[str, CtxEvidence]:
        return {e.id: e for e in [*self.supporting, *self.context]}


@dataclass
class Claim:
    id: str  # c1, c2, ...
    text: str
    evidence_ids: list[str]
    kind: str = FACT


@dataclass
class Draft:
    """What a provider returns. It is validated by the guard before anything is shown."""
    claims: list[Claim]
    caveats: list[str] = field(default_factory=list)
    acknowledges_conflict: bool = False
    provider: str = "extractive"


@dataclass
class Violation:
    code: str
    message: str
    claim_id: str | None = None


@dataclass
class ConfidenceReport:
    model_confidence: dict
    evidence_confidence: dict
    answer_support: dict


@dataclass
class AnswerResult:
    status: str
    text: str  # the answer as shown: claim sentences with [n] markers, or the abstention message
    claims: list[Claim]
    caveats: list[str]
    context_notes: list[Claim]
    confidence: ConfidenceReport
    provider_used: str  # extractive | the LLM provider name
    warnings: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    abstention_reason: str | None = None
