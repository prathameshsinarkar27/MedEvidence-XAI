"""Invalidate a document's evidence index when its evidence is regenerated or deleted."""

import uuid

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models.document import PROCESSING_NOT_PROCESSED, Document
from app.models.evidence_embedding import EvidenceEmbedding


def reset_index(session: Session, document_id: uuid.UUID) -> None:
    """Delete the document's vectors and reset its index status. The caller commits."""
    session.execute(delete(EvidenceEmbedding).where(EvidenceEmbedding.document_id == document_id))
    session.execute(
        update(Document).where(Document.id == document_id).values(
            index_status=PROCESSING_NOT_PROCESSED, index_error_code=None, index_error=None,
            indexed_at=None, indexed_count=None, index_model=None,
        )
    )
