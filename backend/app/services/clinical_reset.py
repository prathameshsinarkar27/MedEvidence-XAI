"""Invalidate clinical evidence when the text, tables or images it was derived from are regenerated."""

import uuid

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import PROCESSING_NOT_PROCESSED, Document
from app.services.index_reset import reset_index


def reset_clinical(session: Session, document_id: uuid.UUID) -> None:
    """Delete the document's evidence and reset its clinical status. The caller commits.

    Evidence points at page numbers, table rows and images of a particular processing run, so it must not
    outlive them; running extraction again regenerates it."""
    reset_index(session, document_id)  # vectors of the old evidence (Phase 6)
    session.execute(delete(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id))
    session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            clinical_status=PROCESSING_NOT_PROCESSED,
            clinical_error_code=None,
            clinical_error=None,
            clinical_processed_at=None,
            clinical_page_count=None,
            clinical_pages_processed=0,
            evidence_count=None,
            clinical_summary=None,
        )
    )
