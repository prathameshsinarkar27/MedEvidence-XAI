"""Response models for the evidence index and retrieval (Phase 6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.clinical import EvidenceOut


class EvidenceRecord(EvidenceOut):
    """A ClinicalEvidence item plus its document's display name: the complete provenance chain in one object
    (document -> page -> table row / image / text span -> region)."""

    document_filename: str


class IndexAccepted(BaseModel):
    document_id: uuid.UUID
    index_status: str


class DocumentIndexStatus(BaseModel):
    document_id: uuid.UUID
    index_status: str  # not_processed | queued | processing | completed | failed
    indexed_count: int | None
    evidence_count: int | None
    index_model: str | None  # embedder used for this document's vectors
    current_model: str  # embedder currently configured
    stale: bool  # indexed with a different embedder than the configured one: re-index to make it searchable
    error_code: str | None
    error_message: str | None
    indexed_at: datetime | None
    note: str


class IndexOverview(BaseModel):
    embedding_backend: str
    embedding_model: str  # the name stored with each vector
    embedding_dimension: int | None  # None while the model has not been loaded
    is_semantic: bool
    embedding_available: bool
    embedding_message: str | None  # how to fix it, when unavailable
    vector_backend: str
    vector_backend_available: bool
    vector_backend_message: str | None
    auto_index: bool
    evidence_total: int
    indexed_evidence: int  # vectors in the current vector space
    indexed_documents: int
    stale_documents: int
    note: str


class RebuildAccepted(BaseModel):
    documents_queued: int
    skipped_in_progress: int


class SearchHit(BaseModel):
    rank: int
    score: float  # cosine similarity of query and evidence text, NOT a probability
    evidence: EvidenceRecord
    embedding_text: str  # exactly what was embedded for this evidence


class SearchResponse(BaseModel):
    query: str
    top_k: int
    embedding_model: str
    is_semantic: bool
    vector_backend: str
    filters: dict
    candidates: int | None  # evidence items eligible after filters (None = no filter applied)
    returned: int
    hits: list[SearchHit]
    note: str


class EvidenceBrowseList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EvidenceRecord]


class EntityCount(BaseModel):
    entity_type: str
    entity_name: str
    evidence_count: int
    document_count: int


class EntityList(BaseModel):
    total: int
    items: list[EntityCount]
