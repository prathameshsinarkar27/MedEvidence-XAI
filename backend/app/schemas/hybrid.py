"""Response models for hybrid retrieval and ranking."""

from pydantic import BaseModel

from app.schemas.evidence_index import EvidenceRecord


class ComponentScore(BaseModel):
    score: float  # 0-1
    weight: float
    contribution: float  # weight * score


class HybridHit(BaseModel):
    rank: int
    final_score: float  # sum of contributions; relative ordering only, not a probability
    evidence: EvidenceRecord
    components: dict[str, ComponentScore]
    matched_terms: list[str]  # query words found in the evidence text (keyword match)
    temporal_note: str | None


class QueryAnalysisOut(BaseModel):
    entities: list[str]  # canonical names resolved from the query (lexicon, incl. synonyms/abbreviations)
    entity_mentions: list[str]
    periods: list[tuple[str, str]]
    recency: str | None
    page_hint: int | None
    keyword_tokens: list[str]
    notes: list[str]


class HybridResponse(BaseModel):
    query: str
    mode: str  # hybrid | semantic | keyword | entity
    top_k: int
    formula: str
    weights: dict[str, float]
    analysis: QueryAnalysisOut
    filters: dict
    candidates: int  # evidence items scored after filtering and candidate generation
    returned: int
    semantic_available: bool
    embedding_model: str | None
    is_semantic: bool
    warnings: list[str]
    hits: list[HybridHit]
    note: str


class RankingConfig(BaseModel):
    formula: str
    components: list[str]
    weights: dict[str, float]
    candidate_pool: int
    descriptions: dict[str, str]
    note: str
