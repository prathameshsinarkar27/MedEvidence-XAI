"""Clinical information extraction endpoints (Phase 5)."""

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_session, get_session_factory
from app.models.document import Document
from app.schemas.clinical import ClinicalAccepted, ClinicalStatusOut, EvidenceList, EvidenceOut
from app.services import clinical as clinical_service
from app.services import documents as document_service

router = APIRouter(prefix="/documents", tags=["clinical-extraction"])

EntityType = Literal["lab_result", "vital_sign", "medication", "condition", "symptom", "date"]
Modality = Literal["text", "ocr", "table", "image_ocr"]
Assertion = Literal["affirmed", "negated", "uncertain", "family_history", "allergy", "discontinued", "planned"]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _require_document(session: Session, document_id: uuid.UUID) -> Document:
    document = document_service.get_document(session, document_id)
    if document is None:
        raise _error(404, "document_not_found", "Document not found.")
    return document


@router.post(
    "/{document_id}/clinical-extraction",
    response_model=ClinicalAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or restart) clinical information extraction",
)
def start_clinical_extraction(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    session_factory: sessionmaker = Depends(get_session_factory),
) -> ClinicalAccepted:
    document = _require_document(session, document_id)
    if not clinical_service.can_run(document):
        raise _error(409, "text_not_processed", "Process the document (text extraction) before extracting clinical information.")
    if not clinical_service.claim_clinical(session, document_id):
        raise _error(409, "processing_in_progress", "Clinical extraction is already running for this document.")
    background_tasks.add_task(clinical_service.run_clinical, session_factory, get_settings(), document_id)
    return ClinicalAccepted(document_id=document_id, clinical_status="queued")


@router.get("/{document_id}/clinical-extraction", response_model=ClinicalStatusOut, summary="Clinical extraction status and counts")
def get_clinical_status(document_id: uuid.UUID, session: Session = Depends(get_session)) -> ClinicalStatusOut:
    return clinical_service.build_status(session, _require_document(session, document_id))


@router.get("/{document_id}/clinical-evidence", response_model=EvidenceList, summary="Extracted clinical evidence (filterable)")
def list_clinical_evidence(
    document_id: uuid.UUID,
    entity_type: EntityType | None = None,
    page_number: int | None = Query(default=None, ge=1),
    modality: Modality | None = None,
    assertion: Assertion | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> EvidenceList:
    _require_document(session, document_id)
    total, rows = clinical_service.list_evidence(
        session, document_id, entity_type=entity_type, page_number=page_number, modality=modality,
        assertion=assertion, min_confidence=min_confidence, limit=limit, offset=offset,
    )
    return EvidenceList(document_id=document_id, total=total, limit=limit, offset=offset,
                        items=[clinical_service.evidence_out(r) for r in rows])


@router.get("/{document_id}/clinical-evidence/{evidence_id}", response_model=EvidenceOut, summary="One evidence item with its full source trail")
def get_clinical_evidence(document_id: uuid.UUID, evidence_id: uuid.UUID, session: Session = Depends(get_session)) -> EvidenceOut:
    _require_document(session, document_id)
    row = clinical_service.get_evidence(session, document_id, evidence_id)
    if row is None:
        raise _error(404, "evidence_not_found", "Evidence not found.")
    return clinical_service.evidence_out(row)
