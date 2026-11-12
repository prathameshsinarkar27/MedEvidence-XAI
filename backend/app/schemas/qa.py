"""Response models for evidence-grounded answers and explainability (Phase 9)."""

from pydantic import BaseModel

from app.schemas.evidence_index import EvidenceRecord
from app.schemas.reasoning import ConflictPairOut, EvidenceStateOut, QuestionUnderstandingOut


class SourceRef(BaseModel):
    """Where a claim comes from: document -> page -> region (open /documents/{id}/pages/{page}/preview to see it)."""
    evidence_id: str
    document_id: str
    document_filename: str
    page_number: int
    source_text: str
    mention_text: str
    modality: str
    region: dict | None
    bbox: dict | None


class ClaimOut(BaseModel):
    id: str
    marker: int
    text: str
    kind: str
    evidence_ids: list[str]
    sources: list[SourceRef]


class EvidenceCard(BaseModel):
    role: str  # supporting | context | conflicting
    evidence: EvidenceRecord
    verification_score: float
    claim_check: str | None
    why_selected: list[str]
    cited_by_claims: list[int]


class ConfidenceOut(BaseModel):
    model_confidence: dict
    evidence_confidence: dict
    answer_support: dict
    note: str


class ProviderInfo(BaseModel):
    requested: str
    used: str
    external_call_made: bool
    fallback: bool


class AnswerResponse(BaseModel):
    question: str
    status: str  # answered | answered_with_caveats | conflict_reported | abstained
    answer: str
    abstention_reason: str | None
    claims: list[ClaimOut]
    caveats: list[str]
    context_notes: list[str]
    confidence: ConfidenceOut
    supporting_evidence: list[EvidenceCard]
    conflicting_evidence: list[EvidenceCard]
    context_evidence: list[EvidenceCard]
    conflicts: list[ConflictPairOut]
    understanding: QuestionUnderstandingOut
    evidence_state: EvidenceStateOut
    provider: ProviderInfo
    warnings: list[str]
    disclaimer: str


class QAConfigOut(BaseModel):
    provider: str
    llm_model: str | None
    llm_base_url: str | None  # shown without credentials
    llm_local: bool | None
    llm_allow_external: bool
    llm_api_key_configured: bool
    abstention_message: str
    statuses: list[str]
    pipeline: list[str]
    note: str
