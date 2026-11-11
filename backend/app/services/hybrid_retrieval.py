"""Hybrid retrieval use-cases (Phase 7): candidate generation, component scoring, fusion.

Semantic scores come from the Phase 6 vector index; keyword scores from an in-memory BM25 index over the same evidence
text; entity/temporal/confidence/source scores from stored fields. The corpus (features + BM25) is rebuilt in memory
when the stored evidence changes. Retrieval returns evidence with a full score breakdown, never an answer.
"""

import logging
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import Document
from app.schemas.evidence_index import EvidenceRecord
from app.schemas.hybrid import (
    ComponentScore,
    HybridHit,
    HybridResponse,
    QueryAnalysisOut,
    RankingConfig,
)
from app.services import evidence_index as index_service
from evidence_index import EmbeddingUnavailableError, VectorBackendUnavailableError, build_embedding_text
from hybrid_retrieval import (
    COMPONENTS,
    FORMULA,
    BM25Index,
    EvidenceFeatures,
    QueryAnalysis,
    ScoredItem,
    Weights,
    analyze_query,
    rank,
    score_components,
)

logger = logging.getLogger(__name__)

MODES = ("hybrid", "semantic", "keyword", "entity")
NOTE = (
    "final_score is a weighted sum of the listed component scores, used only to order evidence; it is not a probability "
    "and not a measure of clinical relevance. Weights are configuration. Ranking quality is reported in "
    "docs/evaluation-retrieval.md for a small synthetic benchmark only; outside it: Not yet evaluated."
)
DESCRIPTIONS = {
    "semantic": "cosine similarity of query and evidence text (Phase 6 vector index), clipped at 0",
    "keyword": "BM25 over the evidence text, divided by the best BM25 among the candidates",
    "entity": "1 if the evidence's canonical entity is named in the query (lexicon synonyms resolved), 0.5 if it contains all its words, else 0",
    "temporal": "only if the query has a date/period or latest/earliest: 1 inside the period (decays outside), recency rank among entity-matched dated evidence; undated = 0",
    "confidence": "the extraction confidence (heuristic score, not a probability)",
    "source": "OCR evidence scaled by Tesseract's mean confidence; text/table = 1; a 'page N' hint halves other pages",
}


@dataclass
class _Corpus:
    fingerprint: tuple
    features: dict[str, EvidenceFeatures]
    bm25: BM25Index


_cache: _Corpus | None = None
_lock = threading.Lock()


def clear_corpus_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _corpus(session: Session) -> _Corpus:
    global _cache
    count, newest = session.execute(select(func.count(), func.max(ClinicalEvidence.created_at))).one()
    fingerprint = (int(count), str(newest))
    with _lock:
        if _cache is not None and _cache.fingerprint == fingerprint:
            return _cache
        pairs = list(session.execute(
            select(ClinicalEvidence, Document.original_filename).join(Document, Document.id == ClinicalEvidence.document_id)
            .order_by(Document.original_filename, ClinicalEvidence.ordinal)))
        rows = [r for r, _ in pairs]
        names = {str(r.id): n for r, n in pairs}
        features = {
            str(r.id): EvidenceFeatures(
                id=str(r.id), document_id=str(r.document_id), page_number=r.page_number, entity_name=r.entity_name,
                modality=r.modality, extraction_confidence=r.extraction_confidence, date_iso=r.date_iso,
                ocr_confidence=r.ocr_confidence, entity_type=r.entity_type, assertion=r.assertion,
                order=(names[str(r.id)], r.ordinal))
            for r in rows
        }
        bm25 = BM25Index({str(r.id): build_embedding_text(r) for r in rows})
        _cache = _Corpus(fingerprint, features, bm25)
        return _cache


def _passes(f: EvidenceFeatures, flt: dict) -> bool:
    if flt.get("document_id") and f.document_id != flt["document_id"]:
        return False
    if flt.get("page_number") and f.page_number != flt["page_number"]:
        return False
    if flt.get("entity_type") and f.entity_type != flt["entity_type"]:
        return False
    if flt.get("entity_name") and f.entity_name.casefold() != flt["entity_name"].strip().casefold():
        return False
    if flt.get("modality") and f.modality != flt["modality"]:
        return False
    if flt.get("assertion") and f.assertion != flt["assertion"]:
        return False
    if flt.get("min_confidence") is not None and f.extraction_confidence < flt["min_confidence"]:
        return False
    if flt.get("date_from") and not (f.date_iso and f.date_iso >= flt["date_from"]):
        return False
    if flt.get("date_to") and not (f.date_iso and f.date_iso <= flt["date_to"]):
        return False
    return True


@dataclass
class Prepared:
    """Everything except the weights: lets the benchmark fuse the same query under many weight sets."""
    analysis: QueryAnalysis
    items: list[ScoredItem]
    eligible: int
    semantic_available: bool
    embedding_model: str | None
    is_semantic: bool
    warnings: list[str]


def prepare(session: Session, settings: Settings, query: str, filters: dict | None = None, *, need_semantic: bool = True,
            strict: bool = True) -> Prepared:
    """Candidate generation + component scores (no weights involved)."""
    flt = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in (filters or {}).items() if v is not None}
    corpus = _corpus(session)
    analysis = analyze_query(query)
    eligible = {i for i, f in corpus.features.items() if _passes(f, flt)}
    warnings: list[str] = []

    semantic: dict[str, float] = {}
    available, model, is_semantic = False, None, False
    if need_semantic:
        try:
            embedder = index_service._embedder(settings)
            model, is_semantic = embedder.name, embedder.is_semantic
            index = index_service._get_index(session, settings, embedder)
        except (EmbeddingUnavailableError, VectorBackendUnavailableError) as exc:
            if strict:
                raise
            warnings.append(f"The semantic component is unavailable and scored 0: {exc}")
            index = None
        if index is None:
            pass
        elif len(index) == 0:
            warnings.append("No evidence vectors exist yet (index the documents): the semantic component is 0.")
        else:
            available = True
            scored = index.search(embedder.embed([query])[0], len(index), eligible)
            semantic = {s.id: s.score for s in scored}
            unindexed = len(eligible) - len(semantic)
            if unindexed > 0:
                warnings.append(f"{unindexed} eligible evidence item(s) have no vector in the current embedding space "
                                "(not indexed or stale); they can only score on the other components.")
    keyword = corpus.bm25.score(analysis.tokens, eligible)

    pool = settings.ranking_candidate_pool
    candidate_ids = set(sorted((i for i in semantic if semantic[i] > 0), key=lambda i: -semantic[i])[:pool])
    candidate_ids |= set(keyword)
    if analysis.entities:
        from hybrid_retrieval.ranking import entity_score
        candidate_ids |= {i for i in eligible if entity_score(corpus.features[i].entity_name, analysis.entities) > 0}
    items = score_components(
        analysis, [corpus.features[i] for i in sorted(candidate_ids)], semantic, keyword,
        {i: corpus.bm25.matched_terms(analysis.tokens, i) for i in candidate_ids})
    return Prepared(analysis, items, len(eligible), available, model, is_semantic, warnings)


def resolve_weights(settings: Settings, mode: str, overrides: dict[str, float | None]) -> Weights:
    if mode in COMPONENTS:
        return Weights.only(mode)
    if mode == "semantic":
        return Weights.only("semantic")
    base = settings.rank_weights.as_dict()
    base.update({k: v for k, v in overrides.items() if v is not None})
    return Weights(**base)


def search(session: Session, settings: Settings, query: str, *, top_k: int, mode: str = "hybrid",
           overrides: dict[str, float | None] | None = None, filters: dict | None = None) -> HybridResponse:
    weights = resolve_weights(settings, mode, overrides or {})
    prepared = prepare(session, settings, query, filters, need_semantic=weights.semantic > 0, strict=(mode == "semantic"))
    ranked = rank(prepared.items, weights)
    ranked = [r for r in ranked if r.final_score > 0][:top_k]
    ids = [uuid.UUID(r.features.id) for r in ranked]
    records: dict[uuid.UUID, EvidenceRecord] = index_service._records(session, ids)
    w = weights.as_dict()
    hits = [
        HybridHit(
            rank=n, final_score=round(r.final_score, 6), evidence=records[uuid.UUID(r.features.id)],
            components={c: ComponentScore(score=round(r.components[c], 6), weight=w[c],
                                          contribution=round(w[c] * r.components[c], 6)) for c in COMPONENTS},
            matched_terms=r.matched_terms, temporal_note=r.temporal_note)
        for n, r in enumerate(ranked, start=1) if uuid.UUID(r.features.id) in records
    ]
    a = prepared.analysis
    active = {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in (filters or {}).items() if v is not None}
    return HybridResponse(
        query=query, mode=mode, top_k=top_k, formula=FORMULA, weights=w,
        analysis=QueryAnalysisOut(entities=a.entities, entity_mentions=a.entity_mentions, periods=a.periods,
                                  recency=a.recency, page_hint=a.page_hint, keyword_tokens=a.tokens, notes=a.notes),
        filters=active, candidates=len(prepared.items), returned=len(hits),
        semantic_available=prepared.semantic_available, embedding_model=prepared.embedding_model,
        is_semantic=prepared.is_semantic, warnings=prepared.warnings, hits=hits, note=NOTE)


def ranking_config(settings: Settings) -> RankingConfig:
    return RankingConfig(formula=FORMULA, components=list(COMPONENTS), weights=settings.rank_weights.as_dict(),
                         candidate_pool=settings.ranking_candidate_pool, descriptions=DESCRIPTIONS, note=NOTE)
