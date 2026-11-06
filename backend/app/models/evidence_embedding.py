"""EvidenceEmbedding: the vector stored for one ClinicalEvidence row (Phase 6).

PostgreSQL is the source of truth for vectors; the FAISS/NumPy index is rebuilt from this table in memory.
`embedding_text` is exactly what was embedded (so it can be inspected and reproduced); `text_sha256` and
`model_name` identify the text and the vector space. Provenance is the foreign key: evidence_id ->
clinical_evidence -> document / page / table / image / region.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.document import utcnow


class EvidenceEmbedding(Base):
    __tablename__ = "evidence_embeddings"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clinical_evidence.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)  # embedder name = vector space identity
    backend: Mapped[str] = mapped_column(String(30), nullable=False)  # hashing | sentence-transformers
    text_version: Mapped[str] = mapped_column(String(10), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32, little-endian, L2-normalised
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_evidence_embeddings_document", "document_id"),
        Index("ix_evidence_embeddings_model", "model_name"),
    )
