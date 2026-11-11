"""Question understanding + evidence verification use-case (Phase 8).

Question -> Phase 7 hybrid retrieval -> verification of every retrieved item -> conflict analysis -> evidence state.
Nothing here writes an answer: the output is structured evidence analysis for Phase 9. No clinical text is logged.
"""

import dataclasses
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.evidence_index import EvidenceRecord
from app.schemas.hybrid import QueryAnalysisOut
from app.schemas.reasoning import (
    ConflictAnalysisOut,
    ConflictPairOut,
    EvidenceStateOut,
    ItemVerificationOut,
    QuestionUnderstandingOut,
    ReasoningConfigOut,
    ReasonOut,
    RetrievalSummary,
    VerificationResponse,
    VerifiedHit,
)
from app.services import hybrid_retrieval as hybrid_service
from evidence_reasoning import (
    CONFLICT_CATEGORIES,
    STATES,
    VERIFY_COMPONENTS,
    VERIFY_FORMULA,
    VEvidence,
    understand_question,
    verify_question,
)
from evidence_reasoning.types import QUESTION_TYPES

logger = logging.getLogger(__name__)

NOTE = (
    "This is an analysis of retrieved evidence, not an answer and not medical advice. Verification scores and evidence states "
    "are heuristic, are not probabilities, and use uncalibrated engineering defaults: Not yet evaluated. A 'supported' state means "
    "the documents contain direct evidence for the question, not that the evidence is clinically correct."
)
DESCRIPTIONS = {
    "relevance": "Phase 7 semantic similarity of question and evidence text (not applicable without vectors)",
    "entity": "1 exact canonical entity match, 0.5 partial, 0 none; type match for 'list the medications' style questions; n/a if no entity",
    "value": "internal consistency of a stated value (plain number, unit present, not flagged implausible); n/a without a value",
    "temporal": "only for questions with a date/period or latest/earliest: inside the period / is the latest value = 1, outside = 0, undated = low",
    "confidence": "the Phase 5 extraction confidence (heuristic, not a probability)",
    "source": "text layer / table = 1; OCR = Tesseract mean confidence / 100",
    "directness": "1 direct (right entity, right kind of statement, value present, constraints met), 0.5 indirect, 0 not relevant",
    "agreement": "(1 + items stating the same finding) / (1 + same + possible contradictions about the same entity)",
}


def understand(question: str) -> QuestionUnderstandingOut:
    return QuestionUnderstandingOut(**dataclasses.asdict(understand_question(question)))


def _to_vevidence(hit, semantic_available: bool) -> VEvidence:
    e = hit.evidence
    return VEvidence(
        id=str(e.evidence_id), document_id=str(e.document_id), document_filename=e.document_filename, page_number=e.page_number,
        entity_type=e.entity_type, entity_name=e.entity_name, assertion=e.assertion, modality=e.modality,
        extraction_confidence=e.extraction_confidence, source_text=e.source_text, source_start=e.source_start,
        source_end=e.source_end, value_text=e.value_text, value_numeric=e.value_numeric, value_comparator=e.value_comparator,
        unit_normalized=e.unit_normalized, date_iso=e.date_iso, ocr_confidence=e.ocr_confidence, attributes=dict(e.attributes or {}),
        retrieval_rank=hit.rank, semantic=hit.components["semantic"].score if semantic_available else None,
        order=(e.document_filename, e.page_number, e.char_start or 0, str(e.evidence_id)))


def verify(session: Session, settings: Settings, question: str, *, top_k: int | None = None,
           document_id: uuid.UUID | None = None) -> VerificationResponse:
    pool = top_k or settings.verify_candidates
    analysis = understand_question(question)
    filters: dict = {"document_id": document_id}
    if len(analysis.requested_entity_types) == 1 and not analysis.entities:
        filters["entity_type"] = analysis.requested_entity_types[0]  # "list the medications": retrieve that type only
    retrieved = hybrid_service.search(session, settings, question, top_k=pool, mode="hybrid", filters=filters)
    evidence = [_to_vevidence(h, retrieved.semantic_available) for h in retrieved.hits]
    result = verify_question(analysis, evidence, settings.reasoning_config)
    logger.info("verification: type=%s retrieved=%d state=%s conflicts=%d", analysis.primary, len(evidence), result.state.state,
                len(result.conflicts.pairs))

    by_id = {i.id: i for i in result.items}
    verification_rank = {i.id: n for n, i in enumerate(sorted(result.items, key=lambda x: (-x.score, x.id)), start=1)}
    hits = [
        VerifiedHit(
            retrieval_rank=h.rank, retrieval_score=h.final_score, retrieval_components=h.components, matched_terms=h.matched_terms,
            temporal_note=h.temporal_note, evidence=h.evidence,
            verification=ItemVerificationOut(
                verification_rank=verification_rank[str(h.evidence.evidence_id)],
                **{k: v for k, v in dataclasses.asdict(by_id[str(h.evidence.evidence_id)]).items() if k != "id"}))
        for h in retrieved.hits
    ]
    state = result.state
    return VerificationResponse(
        question=question,
        understanding=QuestionUnderstandingOut(**dataclasses.asdict(analysis)),
        retrieval=RetrievalSummary(
            mode=retrieved.mode, pool_size=pool, candidates=retrieved.candidates, returned=retrieved.returned,
            formula=retrieved.formula, weights=retrieved.weights, analysis=retrieved.analysis, filters=retrieved.filters,
            semantic_available=retrieved.semantic_available, embedding_model=retrieved.embedding_model,
            is_semantic=retrieved.is_semantic, warnings=retrieved.warnings),
        ranked_evidence=hits,
        conflict_analysis=ConflictAnalysisOut(
            pairs=[ConflictPairOut(**{**dataclasses.asdict(p), "evidence_ids": list(p.evidence_ids)}) for p in result.conflicts.pairs],
            timelines=result.conflicts.timelines, counts=result.conflicts.counts, skipped=result.conflicts.skipped),
        evidence_state=EvidenceStateOut(
            state=state.state, reasons=[ReasonOut(**dataclasses.asdict(r)) for r in state.reasons],
            supporting_evidence_ids=state.supporting_ids, context_evidence_ids=state.context_ids,
            conflicting_evidence_ids=state.conflicting_ids, coverage=state.coverage, claim_assessment=state.claim_assessment),
        note=NOTE)


def reasoning_config(settings: Settings) -> ReasoningConfigOut:
    cfg = settings.reasoning_config
    return ReasoningConfigOut(
        verification_formula=VERIFY_FORMULA, weights=cfg.weights.as_dict(), component_descriptions=DESCRIPTIONS,
        thresholds={"supported_score": cfg.supported_score, "min_relevant_score": cfg.min_relevant_score,
                    "min_semantic_no_entity": cfg.min_semantic_no_entity, "undated_temporal_score": cfg.undated_temporal_score},
        conflict_tolerances={"lab_result": cfg.tolerance_lab, "vital_sign": cfg.tolerance_vital,
                             "medication": cfg.tolerance_medication, "default": cfg.tolerance_default},
        question_types=list(QUESTION_TYPES), evidence_states=list(STATES), conflict_categories=list(CONFLICT_CATEGORIES),
        candidates=settings.verify_candidates, note=NOTE)
