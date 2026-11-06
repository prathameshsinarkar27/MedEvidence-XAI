"""Evidence index use-cases (Phase 6): embed stored ClinicalEvidence, keep vectors in PostgreSQL, search them.

PostgreSQL (`evidence_embeddings`) is the source of truth; an exact FAISS/NumPy index is rebuilt in memory
from it whenever the stored vectors change. Search returns evidence ids, which are resolved back to the full
ClinicalEvidence row (document -> page -> source region), so provenance is never lost.
Nothing here verifies, answers or generates text (Phases 8-9).
"""

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import (
    PROCESSING_COMPLETED,
    PROCESSING_FAILED,
    PROCESSING_IN_PROGRESS,
    PROCESSING_QUEUED,
    PROCESSING_RUNNING,
    Document,
    utcnow,
)
from app.models.evidence_embedding import EvidenceEmbedding
from app.schemas.evidence_index import (
    DocumentIndexStatus,
    EntityCount,
    EvidenceRecord,
    IndexOverview,
    SearchHit,
    SearchResponse,
)
from app.services.clinical import READY_TEXT_STATUSES, evidence_out
from evidence_index import (
    TEXT_VERSION,
    Embedder,
    EmbeddingUnavailableError,
    VectorBackendUnavailableError,
    VectorIndex,
    build_embedding_text,
    create_vector_index,
    get_embedder,
    vector_backend_status,
)

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Evidence indexing was interrupted (the server stopped or restarted). Run it again."
SEARCH_NOTE = (
    "Scores are cosine similarities between the query and each evidence text, not probabilities and not "
    "measures of clinical relevance. Retrieval quality has not been evaluated (Not yet evaluated). "
    "Research prototype - not for clinical use."
)
INDEX_NOTE = (
    "The index stores one vector per extracted evidence item. Retrieval returns evidence, not answers: nothing "
    "is verified or generated at this stage. Not yet evaluated."
)


# ---------------------------------------------------------------- claim / recovery

def claim_index(session: Session, document_id: uuid.UUID) -> bool:
    result = session.execute(
        update(Document)
        .where(Document.id == document_id, Document.index_status.notin_(PROCESSING_IN_PROGRESS))
        .values(index_status=PROCESSING_QUEUED, index_error_code=None, index_error=None)
    )
    session.commit()
    return result.rowcount == 1


def recover_interrupted_index(session_factory: sessionmaker) -> int:
    with session_factory() as session:
        result = session.execute(
            update(Document).where(Document.index_status.in_(PROCESSING_IN_PROGRESS))
            .values(index_status=PROCESSING_FAILED, index_error_code="interrupted", index_error=INTERRUPTED_MESSAGE)
        )
        session.commit()
        return result.rowcount or 0


def _mark_failed(session: Session, document_id: uuid.UUID, code: str, message: str) -> None:
    session.execute(
        update(Document).where(Document.id == document_id).values(
            index_status=PROCESSING_FAILED, index_error_code=code, index_error=message, indexed_at=utcnow())
    )
    session.commit()


# ---------------------------------------------------------------- indexing

def _embedder(settings: Settings) -> Embedder:
    return get_embedder(settings.embedder_config)


def run_index(session_factory: sessionmaker, settings: Settings, document_id: uuid.UUID) -> None:
    """Background entry point. Never raises; always leaves a terminal status."""
    started = time.monotonic()
    with session_factory() as session:
        try:
            _run(session, settings, document_id)
        except Exception:
            logger.exception("Unexpected error while indexing evidence of document %s", document_id)
            session.rollback()
            _mark_failed(session, document_id, "internal_error", "Indexing failed unexpectedly. See the server log.")
    logger.info("Evidence indexing finished for document %s in %.2fs", document_id, time.monotonic() - started)


def _run(session: Session, settings: Settings, document_id: uuid.UUID) -> None:
    document = session.get(Document, document_id)
    if document is None:
        return
    document.index_status = PROCESSING_RUNNING
    session.commit()
    if document.clinical_status not in READY_TEXT_STATUSES:
        _mark_failed(session, document_id, "clinical_not_processed", "Clinical extraction has not completed for this document.")
        return
    try:
        embedder = _embedder(settings)
    except EmbeddingUnavailableError as exc:
        _mark_failed(session, document_id, "embedding_unavailable", str(exc))
        return

    rows = list(session.scalars(select(ClinicalEvidence).where(ClinicalEvidence.document_id == document_id)
                                .order_by(ClinicalEvidence.ordinal)))
    texts = [build_embedding_text(r) for r in rows]
    batch = settings.embedding_batch_size
    vectors = (np.vstack([embedder.embed(texts[i:i + batch]) for i in range(0, len(texts), batch)])
               if texts else np.zeros((0, embedder.dimension), dtype=np.float32))

    # Replace the document's vectors atomically: embedding (the slow, fallible part) is already done.
    session.query(EvidenceEmbedding).filter(EvidenceEmbedding.document_id == document_id).delete()
    now = utcnow()
    for row, text, vector in zip(rows, texts, vectors):
        session.add(EvidenceEmbedding(
            evidence_id=row.id, document_id=document_id, model_name=embedder.name, backend=embedder.backend,
            text_version=TEXT_VERSION, dimension=int(vector.shape[0]), embedding_text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            vector=np.asarray(vector, dtype="<f4").tobytes(), created_at=now,
        ))
    session.execute(update(Document).where(Document.id == document_id).values(
        index_status=PROCESSING_COMPLETED, index_error_code=None, index_error=None, indexed_at=now,
        indexed_count=len(rows), index_model=embedder.name))
    session.commit()


# ---------------------------------------------------------------- in-memory vector index cache

@dataclass
class _Cached:
    fingerprint: tuple
    index: VectorIndex


_cache: dict[tuple[str, str], _Cached] = {}
_lock = threading.Lock()


def _fingerprint(session: Session, model_name: str) -> tuple:
    count, newest = session.execute(
        select(func.count(), func.max(EvidenceEmbedding.created_at)).where(EvidenceEmbedding.model_name == model_name)
    ).one()
    return int(count), str(newest)


def _get_index(session: Session, settings: Settings, embedder: Embedder) -> VectorIndex:
    key = (settings.vector_backend, embedder.name)
    fingerprint = _fingerprint(session, embedder.name)
    with _lock:
        cached = _cache.get(key)
        if cached and cached.fingerprint == fingerprint:
            return cached.index
        rows = session.execute(
            select(EvidenceEmbedding.evidence_id, EvidenceEmbedding.vector)
            .where(EvidenceEmbedding.model_name == embedder.name).order_by(EvidenceEmbedding.evidence_id)
        ).all()
        ids = [str(r[0]) for r in rows]
        matrix = (np.vstack([np.frombuffer(r[1], dtype="<f4") for r in rows]) if rows
                  else np.zeros((0, embedder.dimension), dtype=np.float32))
        index = create_vector_index(settings.vector_backend, ids, matrix)
        _cache[key] = _Cached(fingerprint, index)
        return index


def clear_index_cache() -> None:
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------- search

def _evidence_filters(query, *, document_id=None, page_number=None, entity_type=None, entity_name=None,
                      modality=None, assertion=None, min_confidence=None):
    for column, value in ((ClinicalEvidence.document_id, document_id), (ClinicalEvidence.page_number, page_number),
                          (ClinicalEvidence.entity_type, entity_type), (ClinicalEvidence.modality, modality),
                          (ClinicalEvidence.assertion, assertion)):
        if value is not None:
            query = query.where(column == value)
    if entity_name:
        query = query.where(func.lower(ClinicalEvidence.entity_name) == entity_name.strip().lower())
    if min_confidence is not None:
        query = query.where(ClinicalEvidence.extraction_confidence >= min_confidence)
    return query


def _records(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, EvidenceRecord]:
    if not ids:
        return {}
    rows = session.execute(
        select(ClinicalEvidence, Document.original_filename)
        .join(Document, Document.id == ClinicalEvidence.document_id).where(ClinicalEvidence.id.in_(ids))
    ).all()
    return {ev.id: EvidenceRecord(**evidence_out(ev).model_dump(), document_filename=name) for ev, name in rows}


def search(session: Session, settings: Settings, query: str, *, top_k: int, min_score: float | None = None,
           **filters) -> SearchResponse:
    """Semantic search. Raises EmbeddingUnavailableError / VectorBackendUnavailableError (mapped to 503)."""
    embedder = _embedder(settings)
    active = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in filters.items() if v is not None}
    allowed = None
    candidates = None
    if active:
        id_query = _evidence_filters(
            select(ClinicalEvidence.id).join(EvidenceEmbedding, EvidenceEmbedding.evidence_id == ClinicalEvidence.id)
            .where(EvidenceEmbedding.model_name == embedder.name), **filters)
        allowed = {str(i) for i in session.scalars(id_query)}
        candidates = len(allowed)
    index = _get_index(session, settings, embedder)
    scored = index.search(embedder.embed([query])[0], top_k, allowed)
    if min_score is not None:
        scored = [s for s in scored if s.score >= min_score]
    ids = [uuid.UUID(s.id) for s in scored]
    records = _records(session, ids)
    texts = dict(session.execute(select(EvidenceEmbedding.evidence_id, EvidenceEmbedding.embedding_text)
                                 .where(EvidenceEmbedding.evidence_id.in_(ids))).all()) if ids else {}
    hits = [SearchHit(rank=n, score=round(s.score, 6), evidence=records[i], embedding_text=texts.get(i, ""))
            for n, (s, i) in enumerate(zip(scored, ids), start=1) if i in records]
    if min_score is not None:
        active["min_score"] = min_score
    return SearchResponse(query=query, top_k=top_k, embedding_model=embedder.name, is_semantic=embedder.is_semantic,
                          vector_backend=index.backend, filters=active, candidates=candidates, returned=len(hits),
                          hits=hits, note=SEARCH_NOTE)


# ---------------------------------------------------------------- structured retrieval

def browse(session: Session, *, limit: int, offset: int, **filters) -> tuple[int, list[EvidenceRecord]]:
    """Retrieve by document / page / entity / type / modality (no embeddings involved)."""
    query = _evidence_filters(select(ClinicalEvidence), **filters)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    ids = list(session.scalars(
        query.order_by(ClinicalEvidence.document_id, ClinicalEvidence.ordinal).limit(limit).offset(offset)
        .with_only_columns(ClinicalEvidence.id)))
    records = _records(session, ids)
    return int(total), [records[i] for i in ids if i in records]


def get_record(session: Session, evidence_id: uuid.UUID) -> EvidenceRecord | None:
    return _records(session, [evidence_id]).get(evidence_id)


def list_entities(session: Session, *, entity_type=None, document_id=None, limit=500) -> tuple[int, list[EntityCount]]:
    query = select(ClinicalEvidence.entity_type, ClinicalEvidence.entity_name, func.count(),
                   func.count(func.distinct(ClinicalEvidence.document_id)))
    query = _evidence_filters(query, entity_type=entity_type, document_id=document_id)
    rows = session.execute(query.group_by(ClinicalEvidence.entity_type, ClinicalEvidence.entity_name)
                           .order_by(func.count().desc(), ClinicalEvidence.entity_name)).all()
    items = [EntityCount(entity_type=t, entity_name=n, evidence_count=int(c), document_count=int(d)) for t, n, c, d in rows]
    return len(items), items[:limit]


# ---------------------------------------------------------------- status

def _embedder_state(settings: Settings) -> tuple[Embedder | None, str | None]:
    try:
        return _embedder(settings), None
    except EmbeddingUnavailableError as exc:
        return None, str(exc)


def current_model_name(settings: Settings) -> str:
    """Name of the configured vector space, without loading a model."""
    cfg = settings.embedder_config
    if cfg.backend == "hashing":
        from evidence_index import HASHING_VERSION
        return f"hashing-v{HASHING_VERSION}-d{cfg.dimension}"
    return cfg.model


def document_status(session: Session, settings: Settings, document: Document) -> DocumentIndexStatus:
    current = current_model_name(settings)
    stale = document.index_status == PROCESSING_COMPLETED and document.index_model not in (None, current)
    return DocumentIndexStatus(
        document_id=document.id, index_status=document.index_status, indexed_count=document.indexed_count,
        evidence_count=document.evidence_count, index_model=document.index_model, current_model=current, stale=stale,
        error_code=document.index_error_code, error_message=document.index_error, indexed_at=document.indexed_at,
        note=INDEX_NOTE)


def overview(session: Session, settings: Settings) -> IndexOverview:
    embedder, message = _embedder_state(settings)
    current = embedder.name if embedder else current_model_name(settings)
    ok, vmessage = vector_backend_status(settings.vector_backend)
    indexed = session.scalar(select(func.count()).select_from(EvidenceEmbedding).where(EvidenceEmbedding.model_name == current)) or 0
    docs = session.scalar(select(func.count(func.distinct(EvidenceEmbedding.document_id))).where(EvidenceEmbedding.model_name == current)) or 0
    stale = session.scalar(select(func.count(func.distinct(EvidenceEmbedding.document_id))).where(EvidenceEmbedding.model_name != current)) or 0
    total = session.scalar(select(func.count()).select_from(ClinicalEvidence)) or 0
    return IndexOverview(
        embedding_backend=settings.embedding_backend, embedding_model=current,
        embedding_dimension=embedder.dimension if embedder else (settings.embedding_dimension if settings.embedding_backend == "hashing" else None),
        is_semantic=settings.embedding_backend != "hashing", embedding_available=embedder is not None,
        embedding_message=message, vector_backend=settings.vector_backend, vector_backend_available=ok,
        vector_backend_message=vmessage, auto_index=settings.auto_index_evidence, evidence_total=int(total),
        indexed_evidence=int(indexed), indexed_documents=int(docs), stale_documents=int(stale), note=INDEX_NOTE)


def rebuild_all(session_factory: sessionmaker, settings: Settings, document_ids: list[uuid.UUID]) -> None:
    """Background: (re)index each claimed document in turn."""
    for document_id in document_ids:
        run_index(session_factory, settings, document_id)
        
        
def claim_all(session: Session) -> tuple[list[uuid.UUID], int]:
    """Claim every document that has finished clinical extraction. Returns (claimed ids, skipped because busy)."""
    ids = list(session.scalars(select(Document.id).where(Document.clinical_status.in_(READY_TEXT_STATUSES))))
    claimed = [i for i in ids if claim_index(session, i)]
    return claimed, len(ids) - len(claimed)
