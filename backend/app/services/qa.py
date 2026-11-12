"""Evidence-grounded question answering use-case (Phase 9).

Question -> Phase 8 verification (retrieval, ranking, verification, conflict detection, evidence state) -> answer generation from
the verified evidence context only -> grounding guard -> claim-to-source mapping, confidence report and selection reasons.
No clinical text is logged and the LLM api key is never returned.
"""

import logging
import re
import uuid
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.qa import (
    AnswerResponse,
    ClaimOut,
    ConfidenceOut,
    EvidenceCard,
    ProviderInfo,
    QAConfigOut,
    SourceRef,
)
from app.schemas.reasoning import ConflictPairOut, EvidenceStateOut, QuestionUnderstandingOut, ReasonOut
from app.services import reasoning as reasoning_service
from evidence_qa import (
    ABSTENTION_MESSAGE,
    DISCLAIMER,
    STATUSES,
    AnswerContext,
    CtxConflict,
    CtxEvidence,
    build_answer,
    is_local_url,
    selection_reasons,
)

logger = logging.getLogger(__name__)

PIPELINE = ["Question understanding", "Evidence retrieval", "Evidence ranking", "Evidence verification", "Conflict detection",
            "Confidence estimation", "Answer generation", "Evidence attribution", "Explainable response"]
NOTE = ("Answers restate what the uploaded documents state. They are not a diagnosis or treatment recommendation. Confidence "
        "figures are heuristic engineering values, not probabilities and not medical certainty: Not yet evaluated.")


def _ctx_evidence(hit) -> CtxEvidence:
    e, v = hit.evidence, hit.verification
    return CtxEvidence(
        id=str(e.evidence_id), entity_name=e.entity_name, entity_type=e.entity_type, assertion=e.assertion,
        document_filename=e.document_filename, page_number=e.page_number, source_text=e.source_text, mention_text=e.mention_text,
        value_text=e.value_text, value_comparator=e.value_comparator, unit_text=e.unit_text, date_iso=e.date_iso, date_text=e.date_text,
        modality=e.modality, extraction_confidence=e.extraction_confidence, ocr_confidence=e.ocr_confidence, evidence_score=v.score,
        role=v.role, claim_check=v.claim_check,
        selection={"retrieval_rank": hit.retrieval_rank,
                   "retrieval_components": {k: c.model_dump() for k, c in hit.retrieval_components.items()},
                   "terms": {k: t.model_dump() for k, t in v.terms.items()}, "constraints": v.constraints,
                   "directness_reasons": v.directness_reasons, "requested": None, "recency": None})


def build_context(verified) -> AnswerContext:
    """The verified evidence context handed to the answer generator: supporting items, plus items involved in a conflict."""
    u, st = verified.understanding, verified.evidence_state
    hits = {str(h.evidence.evidence_id): h for h in verified.ranked_evidence}
    items = {i: _ctx_evidence(h) for i, h in hits.items()}
    for item in items.values():
        item.selection["requested"], item.selection["recency"] = u.requested, u.recency
    support = [i for i in st.supporting_evidence_ids if i in items]
    keep_ctx = [i for i in [*st.conflicting_evidence_ids, *st.context_evidence_ids] if i in items and i not in support]
    conflicts = [CtxConflict(evidence_ids=tuple(p.evidence_ids), entity_name=p.entity_name, category=p.category, strength=p.strength,
                             in_scope=p.in_scope, direction=(p.details or {}).get("direction"))
                 for p in verified.conflict_analysis.pairs if all(i in items for i in p.evidence_ids)]
    return AnswerContext(
        question=verified.question, primary_type=u.primary, requested=list(u.requested), entities=list(u.entities), recency=u.recency,
        periods=[tuple(p) for p in u.periods], state=st.state, state_reasons=[(r.code, r.text, r.kind) for r in st.reasons],
        advice_request=u.advice_request, supporting=[items[i] for i in support], context=[items[i] for i in dict.fromkeys(keep_ctx)],
        conflicting_ids=[i for i in st.conflicting_evidence_ids if i in items], conflicts=conflicts, claim_assessment=st.claim_assessment,
        value_constraint_texts=[c.text for c in u.value_constraints], coverage=dict(st.coverage))


def _source(hit) -> SourceRef:
    e = hit.evidence
    return SourceRef(
        evidence_id=str(e.evidence_id), document_id=str(e.document_id), document_filename=e.document_filename, page_number=e.page_number,
        source_text=e.source_text, mention_text=e.mention_text, modality=e.modality,
        region=e.region.model_dump() if e.region else None, bbox=e.bbox.model_dump() if e.bbox else None)


def answer(session: Session, settings: Settings, question: str, *, top_k: int | None = None,
           document_id: uuid.UUID | None = None) -> AnswerResponse:
    verified = reasoning_service.verify(session, settings, question, top_k=top_k, document_id=document_id)
    ctx = build_context(verified)
    provider = settings.llm
    result = build_answer(ctx, provider)
    hits = {str(h.evidence.evidence_id): h for h in verified.ranked_evidence}
    cited: dict[str, list[int]] = {}
    claims = []
    for n, c in enumerate(result.claims, start=1):
        for i in c.evidence_ids:
            cited.setdefault(i, []).append(n)
        claims.append(ClaimOut(id=c.id, marker=n, text=c.text, kind=c.kind, evidence_ids=list(c.evidence_ids),
                               sources=[_source(hits[i]) for i in c.evidence_ids if i in hits]))
    conflicting = set(ctx.conflicting_ids)
    shown: set[str] = set()

    def cards(role: str, items: list[CtxEvidence]) -> list[EvidenceCard]:
        out = []
        for e in items:
            if e.id in shown:
                continue
            shown.add(e.id)
            out.append(EvidenceCard(role=role, evidence=hits[e.id].evidence, verification_score=e.evidence_score, claim_check=e.claim_check,
                                    why_selected=selection_reasons(e, conflicting), cited_by_claims=cited.get(e.id, [])))
        return out

    abstained = result.status == "abstained"
    by_id = {e.id: e for e in [*ctx.supporting, *ctx.context]}
    conflict_cards = cards("conflicting", [by_id[i] for i in ctx.conflicting_ids if i in by_id]) if not abstained or ctx.state == "conflicting" else []
    support_cards = cards("supporting", ctx.supporting) if not abstained else []
    context_cards = cards("context", ctx.context)
    external = bool(provider) and result.provider_used != "extractive" and provider.external
    logger.info("qa: type=%s state=%s status=%s provider=%s claims=%d", ctx.primary_type, ctx.state, result.status, result.provider_used,
                len(result.claims))
    return AnswerResponse(
        question=question, status=result.status, answer=result.text, abstention_reason=result.abstention_reason, claims=claims,
        caveats=result.caveats, context_notes=[c.text for c in result.context_notes],
        confidence=ConfidenceOut(**{k: v for k, v in vars(result.confidence).items()}, note=NOTE),
        supporting_evidence=support_cards, conflicting_evidence=conflict_cards, context_evidence=context_cards,
        conflicts=[p for p in verified.conflict_analysis.pairs if p.in_scope or p.category == "possible_contradiction"],
        understanding=verified.understanding, evidence_state=verified.evidence_state,
        provider=ProviderInfo(requested=settings.llm_provider, used=result.provider_used, external_call_made=external,
                              fallback=bool(provider) and result.provider_used == "extractive"),
        warnings=result.warnings + verified.retrieval.warnings, disclaimer=DISCLAIMER)


def qa_config(settings: Settings) -> QAConfigOut:
    llm = settings.llm_provider == "openai_compatible"
    url = settings.llm_base_url.strip() if llm else None
    safe_url = None
    if url:
        parsed = urlparse(url)
        safe_url = re.sub(r"//[^/@]*@", "//", url) if parsed.username else url
    return QAConfigOut(
        provider=settings.llm_provider, llm_model=(settings.llm_model.strip() or None) if llm else None, llm_base_url=safe_url,
        llm_local=is_local_url(url) if url else None, llm_allow_external=settings.llm_allow_external,
        llm_api_key_configured=bool(settings.llm_api_key), abstention_message=ABSTENTION_MESSAGE, statuses=list(STATUSES),
        pipeline=PIPELINE, note=NOTE)
