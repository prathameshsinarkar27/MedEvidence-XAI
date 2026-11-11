"""Evidence index and retrieval endpoints (Phase 6)."""

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_session, get_session_factory
from app.schemas.hybrid import HybridResponse, RankingConfig
from app.schemas.evidence_index import (
    DocumentIndexStatus,
    EntityList,
    EvidenceBrowseList,
    EvidenceRecord,
    IndexAccepted,
    IndexOverview,
    RebuildAccepted,
    SearchResponse,
)
from app.services import documents as document_service
from app.services import evidence_index as index_service
from app.services import hybrid_retrieval as hybrid_service
from evidence_index import EmbeddingUnavailableError, VectorBackendUnavailableError

documents_router = APIRouter(prefix="/documents", tags=["evidence-index"])
router = APIRouter(prefix="/evidence", tags=["evidence-retrieval"])

EntityType = Literal["lab_result", "vital_sign", "medication", "condition", "symptom", "date"]
Modality = Literal["text", "ocr", "table", "image_ocr"]
Assertion = Literal["affirmed", "negated", "uncertain", "family_history", "allergy", "discontinued", "planned"]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _require_document(session: Session, document_id: uuid.UUID):
    document = document_service.get_document(session, document_id)
    if document is None:
        raise _error(404, "document_not_found", "Document not found.")
    return document


# ------------------------------------------------------------ per-document indexing

@documents_router.post("/{document_id}/evidence-index", response_model=IndexAccepted, status_code=status.HTTP_202_ACCEPTED,
                       summary="Index (or re-index) a document's clinical evidence")
def start_indexing(document_id: uuid.UUID, background_tasks: BackgroundTasks, session: Session = Depends(get_session),
                   session_factory: sessionmaker = Depends(get_session_factory)) -> IndexAccepted:
    document = _require_document(session, document_id)
    if document.clinical_status not in index_service.READY_TEXT_STATUSES:
        raise _error(409, "clinical_not_processed", "Run clinical information extraction before indexing evidence.")
    if not index_service.claim_index(session, document_id):
        raise _error(409, "processing_in_progress", "Indexing is already running for this document.")
    background_tasks.add_task(index_service.run_index, session_factory, get_settings(), document_id)
    return IndexAccepted(document_id=document_id, index_status="queued")


@documents_router.get("/{document_id}/evidence-index", response_model=DocumentIndexStatus, summary="Evidence index status of a document")
def get_indexing_status(document_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentIndexStatus:
    return index_service.document_status(session, get_settings(), _require_document(session, document_id))


# ------------------------------------------------------------ index overview / rebuild

@router.get("/index", response_model=IndexOverview, summary="Embedding model, vector backend and index counts")
def index_overview(session: Session = Depends(get_session)) -> IndexOverview:
    return index_service.overview(session, get_settings())


@router.post("/index/rebuild", response_model=RebuildAccepted, status_code=status.HTTP_202_ACCEPTED,
             summary="Re-index every document that has clinical evidence (e.g. after changing the embedding model)")
def rebuild_index(background_tasks: BackgroundTasks, session: Session = Depends(get_session),
                  session_factory: sessionmaker = Depends(get_session_factory)) -> RebuildAccepted:
    claimed, skipped = index_service.claim_all(session)
    background_tasks.add_task(index_service.rebuild_all, session_factory, get_settings(), claimed)
    return RebuildAccepted(documents_queued=len(claimed), skipped_in_progress=skipped)


# ------------------------------------------------------------ retrieval

@router.get("/search", response_model=SearchResponse, summary="Search evidence by similarity to a free-text query")
def search_evidence(
    q: str = Query(min_length=1, max_length=500, description="Free-text query"),
    top_k: int = Query(default=10, ge=1),
    min_score: float | None = Query(default=None, ge=-1, le=1),
    document_id: uuid.UUID | None = None,
    page_number: int | None = Query(default=None, ge=1),
    entity_type: EntityType | None = None,
    entity_name: str | None = Query(default=None, max_length=200),
    modality: Modality | None = None,
    assertion: Assertion | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    session: Session = Depends(get_session),
) -> SearchResponse:
    settings = get_settings()
    query = q.strip()
    if not query:
        raise _error(422, "empty_query", "The query is empty.")
    if top_k > settings.search_max_top_k:
        raise _error(422, "top_k_too_large", f"top_k must be at most {settings.search_max_top_k}.")
    try:
        return index_service.search(
            session, settings, query, top_k=top_k, min_score=min_score, document_id=document_id,
            page_number=page_number, entity_type=entity_type, entity_name=entity_name, modality=modality,
            assertion=assertion, min_confidence=min_confidence)
    except EmbeddingUnavailableError as exc:
        raise _error(503, "embedding_unavailable", str(exc)) from exc
    except VectorBackendUnavailableError as exc:
        raise _error(503, "vector_backend_unavailable", str(exc)) from exc


@router.get("/ranking-config", response_model=RankingConfig, summary="Ranking formula, components and the configured weights")
def get_ranking_config() -> RankingConfig:
    return hybrid_service.ranking_config(get_settings())


@router.get("/hybrid-search", response_model=HybridResponse,
            summary="Hybrid retrieval: semantic + keyword + entity + temporal + confidence + source, with a score breakdown")
def hybrid_search(
    q: str = Query(min_length=1, max_length=500),
    top_k: int = Query(default=10, ge=1),
    mode: Literal["hybrid", "semantic", "keyword", "entity"] = "hybrid",
    w_semantic: float | None = Query(default=None, ge=0, le=100),
    w_keyword: float | None = Query(default=None, ge=0, le=100),
    w_entity: float | None = Query(default=None, ge=0, le=100),
    w_temporal: float | None = Query(default=None, ge=0, le=100),
    w_confidence: float | None = Query(default=None, ge=0, le=100),
    w_source: float | None = Query(default=None, ge=0, le=100),
    document_id: uuid.UUID | None = None,
    page_number: int | None = Query(default=None, ge=1),
    entity_type: EntityType | None = None,
    entity_name: str | None = Query(default=None, max_length=200),
    modality: Modality | None = None,
    assertion: Assertion | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Evidence date >= (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Evidence date <= (YYYY-MM-DD)"),
    session: Session = Depends(get_session),
) -> HybridResponse:
    settings = get_settings()
    query = q.strip()
    if not query:
        raise _error(422, "empty_query", "The query is empty.")
    if top_k > settings.search_max_top_k:
        raise _error(422, "top_k_too_large", f"top_k must be at most {settings.search_max_top_k}.")
    for value in (date_from, date_to):
        if value:
            try:
                __import__("datetime").date.fromisoformat(value)
            except ValueError:
                raise _error(422, "invalid_date", "Dates must be real calendar dates (YYYY-MM-DD).")
    try:
        return hybrid_service.search(
            session, settings, query, top_k=top_k, mode=mode,
            overrides={"semantic": w_semantic, "keyword": w_keyword, "entity": w_entity, "temporal": w_temporal,
                       "confidence": w_confidence, "source": w_source},
            filters={"document_id": document_id, "page_number": page_number, "entity_type": entity_type,
                     "entity_name": entity_name, "modality": modality, "assertion": assertion,
                     "min_confidence": min_confidence, "date_from": date_from, "date_to": date_to})
    except EmbeddingUnavailableError as exc:
        raise _error(503, "embedding_unavailable", str(exc)) from exc
    except VectorBackendUnavailableError as exc:
        raise _error(503, "vector_backend_unavailable", str(exc)) from exc


@router.get("/entities", response_model=EntityList, summary="Distinct entity names with counts (for retrieval by entity)")
def list_entities(entity_type: EntityType | None = None, document_id: uuid.UUID | None = None,
                  limit: int = Query(default=500, ge=1, le=2000), session: Session = Depends(get_session)) -> EntityList:
    total, items = index_service.list_entities(session, entity_type=entity_type, document_id=document_id, limit=limit)
    return EntityList(total=total, items=items)


@router.get("", response_model=EvidenceBrowseList,
            summary="Retrieve evidence by document, page, entity, type or modality (structured, no embeddings)")
def browse_evidence(
    document_id: uuid.UUID | None = None,
    page_number: int | None = Query(default=None, ge=1),
    entity_type: EntityType | None = None,
    entity_name: str | None = Query(default=None, max_length=200, description="Exact canonical name, case-insensitive"),
    modality: Modality | None = None,
    assertion: Assertion | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> EvidenceBrowseList:
    total, items = index_service.browse(
        session, limit=limit, offset=offset, document_id=document_id, page_number=page_number, entity_type=entity_type,
        entity_name=entity_name, modality=modality, assertion=assertion, min_confidence=min_confidence)
    return EvidenceBrowseList(total=total, limit=limit, offset=offset, items=items)


@router.get("/{evidence_id}", response_model=EvidenceRecord, summary="One evidence item with its full provenance")
def get_evidence(evidence_id: uuid.UUID, session: Session = Depends(get_session)) -> EvidenceRecord:
    record = index_service.get_record(session, evidence_id)
    if record is None:
        raise _error(404, "evidence_not_found", "Evidence not found.")
    return record
