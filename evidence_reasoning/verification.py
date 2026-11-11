"""Per-evidence verification: how well does ONE retrieved evidence item address the question?

    evidence_score = sum(w_c * c) / sum(w_c)      over the components c that apply (weights are configuration)

relevance     Phase 7 semantic similarity of question and evidence text (not applicable when no vectors are available)
entity        1 exact canonical match, 0.5 the evidence entity contains the question entity's words, 0 otherwise;
              for "list the medications" style questions: 1 when the evidence type is the requested type.
              Not applicable when the question names no entity
value         internal consistency of a stated value: 1; 0.75 if only a comparator ("<5"); 0.5 if a laboratory value has no
              unit; 0 if extraction flagged it implausible. Not applicable to evidence without a value
temporal      only if the question has a date/period or latest/earliest: 1 date inside the period / is the latest (earliest)
              dated value of that entity; 0 outside; a fixed low score for undated evidence (the time cannot be confirmed)
confidence    the Phase 5 extraction confidence (heuristic, not a probability)
source        text layer / table = 1; OCR = Tesseract's mean confidence / 100 (0.5 if unknown)
directness    1 direct, 0.5 indirect, 0 not relevant (see `_directness`)
agreement     (1 + n_agree) / (1 + n_agree + n_contradict): other items stating the same finding raise it only up to 1,
              possible contradictions about the same entity lower it

Scores order and gate evidence; they are not probabilities and carry no clinical meaning.
"""

from evidence_reasoning.types import (
    POSSIBLE_CONTRADICTION,
    VALUED_TYPES,
    VERIFY_COMPONENTS,
    ConflictAnalysis,
    ItemVerification,
    QuestionAnalysis,
    ReasoningConfig,
    ValueConstraint,
    VEvidence,
)
from hybrid_retrieval import entity_score

_PATIENT_ASSERTIONS = ("affirmed", "negated", "uncertain")
_ASSERTION_NOTES = {
    "negated": "states the finding is absent (negated)",
    "uncertain": "states the finding with uncertainty (hedged)",
    "family_history": "is about family history, not the patient",
    "allergy": "is an allergy statement",
    "discontinued": "is about a discontinued medication",
    "planned": "is about a planned (not current) medication",
}
_DIRECTNESS_VALUE = {"direct": 1.0, "indirect": 0.5, "not_relevant": 0.0}


def entity_agreement(ev: VEvidence, q: QuestionAnalysis) -> float | None:
    if q.entities:
        return entity_score(ev.entity_name, q.entities)
    if q.requested_entity_types:
        return 1.0 if ev.entity_type in q.requested_entity_types else 0.0
    return None


def assertion_fits(ev: VEvidence, q: QuestionAnalysis) -> tuple[bool, str | None]:
    note = _ASSERTION_NOTES.get(ev.assertion)
    if q.assertion_focus:
        return ev.assertion == q.assertion_focus, note
    return ev.assertion in _PATIENT_ASSERTIONS, note


def recency_targets(evidence: list[VEvidence], q: QuestionAnalysis) -> dict[str, str]:
    """Per entity: the latest (or earliest) date among dated, entity-agreeing, patient-assertion evidence."""
    if not q.recency:
        return {}
    dates: dict[str, list[str]] = {}
    for ev in evidence:
        if ev.date_iso and (entity_agreement(ev, q) or 0) > 0 and assertion_fits(ev, q)[0]:
            dates.setdefault(ev.entity_name, []).append(ev.date_iso)
    pick = max if q.recency == "latest" else min
    return {name: pick(ds) for name, ds in dates.items()}


def constraint_status(ev: VEvidence, q: QuestionAnalysis, targets: dict[str, str]) -> dict[str, str]:
    status = {"period": "n/a", "page": "n/a", "recency": "n/a"}
    if q.periods:
        status["period"] = "unknown" if not ev.date_iso else (
            "met" if any(s <= ev.date_iso <= e for s, e in q.periods) else "unmet")
    if q.page_hint:
        status["page"] = "met" if ev.page_number == q.page_hint else "unmet"
    if q.recency:
        target = targets.get(ev.entity_name)
        status["recency"] = "unknown" if not ev.date_iso or target is None else ("met" if ev.date_iso == target else "unmet")
    return status


def _satisfies(x: float, c: ValueConstraint) -> bool:
    return {"=": abs(x - c.value) < 1e-9, ">": x > c.value, ">=": x >= c.value, "<": x < c.value, "<=": x <= c.value}[c.comparator]


def claim_check(ev: VEvidence, q: QuestionAnalysis) -> str | None:
    """Does this evidence's value agree with a value the question states? Informational; it never changes the state."""
    if not q.value_constraints:
        return None
    if ev.value_comparator or ev.value_numeric is None:
        return "undetermined"
    results: list[bool] = []
    for c in q.value_constraints:
        if c.unit and c.unit != ev.unit_normalized:
            continue
        if c.value2 is not None:  # blood-pressure pair
            sys_, dia = ev.attributes.get("systolic"), ev.attributes.get("diastolic")
            if sys_ is None or dia is None:
                continue
            results.append(sys_ == c.value and dia == c.value2)
        else:
            results.append(_satisfies(float(ev.value_numeric), c))
    return "undetermined" if not results else "confirms" if all(results) else "contradicts"


def _value_consistency(ev: VEvidence) -> tuple[float | None, str]:
    if ev.value_text is None:
        return None, "no value on this evidence"
    if ev.attributes.get("implausible_value"):
        return 0.0, "extraction flagged the value as physiologically implausible"
    score, note = 1.0, "value present and plain"
    if ev.entity_type == "lab_result" and ev.unit_normalized is None:
        score, note = 0.5, "laboratory value without a recognised unit"
    if ev.value_comparator:
        score, note = min(score, 0.75), f"value given only as a comparison ({ev.value_comparator})"
    return score, note


def _source(ev: VEvidence) -> tuple[float, str]:
    if ev.modality in ("ocr", "image_ocr"):
        if ev.ocr_confidence is None:
            return 0.5, "OCR evidence with unknown OCR confidence"
        return max(0.0, min(1.0, ev.ocr_confidence / 100.0)), f"OCR evidence (Tesseract mean confidence {ev.ocr_confidence:.0f}/100)"
    return 1.0, "text layer or detected table"


def _directness(ev: VEvidence, q: QuestionAnalysis, agree: float | None, fits: bool, status: dict[str, str]) -> tuple[str, list[str]]:
    if agree is not None and agree == 0:
        return "not_relevant", ["entity_mismatch"]
    reasons: list[str] = []
    if agree is None:
        reasons.append("entity_not_identified")
    elif agree < 1.0:
        reasons.append("entity_only_partially_matches")
    if not fits:
        reasons.append("assertion_does_not_fit_question")
    if "value" in q.requested and ev.entity_type in VALUED_TYPES and ev.value_text is None:
        reasons.append("no_value_stated")
    if status["page"] == "unmet":
        reasons.append("other_page")
    if status["period"] == "unmet":
        reasons.append("outside_period")
    elif status["period"] == "unknown":
        reasons.append("date_unknown")
    if status["recency"] == "unknown":
        reasons.append("recency_cannot_be_established")
    return ("direct" if not reasons else "indirect"), reasons


def verify_item(ev: VEvidence, q: QuestionAnalysis, targets: dict[str, str], conflicts: ConflictAnalysis,
                cfg: ReasoningConfig) -> ItemVerification:
    agree = entity_agreement(ev, q)
    fits, assertion_note = assertion_fits(ev, q)
    status = constraint_status(ev, q, targets)
    directness, dreasons = _directness(ev, q, agree, fits, status)

    corroborating = conflicts.agreements.get(ev.id, [])
    conflict_ids = sorted({i for p in conflicts.pairs if p.category == POSSIBLE_CONTRADICTION and ev.id in p.evidence_ids
                           for i in p.evidence_ids if i != ev.id})
    value_score, value_note = _value_consistency(ev)
    source_score, source_note = _source(ev)
    temporal: tuple[float | None, str]
    if q.periods or q.recency:
        key = "period" if q.periods else "recency"
        temporal = {"met": (1.0, f"{key} satisfied"), "unmet": (0.0, f"{key} not satisfied"),
                    "unknown": (cfg.undated_temporal_score, "time cannot be confirmed (no usable date)")}[status[key]]
    else:
        temporal = (None, "the question has no time constraint")
    raw = {
        "relevance": (None if ev.semantic is None else max(0.0, min(1.0, ev.semantic)),
                      "semantic similarity from retrieval" if ev.semantic is not None else "semantic component unavailable"),
        "entity": (agree, "entity agreement" if agree is not None else "the question names no entity"),
        "value": (value_score, value_note),
        "temporal": temporal,
        "confidence": (max(0.0, min(1.0, ev.extraction_confidence)), "extraction confidence (heuristic)"),
        "source": (source_score, source_note),
        "directness": (_DIRECTNESS_VALUE[directness], ", ".join(dreasons) or "addresses the question directly"),
        "agreement": ((1 + len(corroborating)) / (1 + len(corroborating) + len(conflict_ids)),
                      f"{len(corroborating)} item(s) state the same finding, {len(conflict_ids)} possible contradiction(s)"),
    }
    weights = cfg.weights.as_dict()
    applicable = [c for c in VERIFY_COMPONENTS if raw[c][0] is not None]
    total_w = sum(weights[c] for c in applicable)
    terms: dict[str, dict] = {}
    score = 0.0
    for c in VERIFY_COMPONENTS:
        s, note = raw[c]
        contrib = None if s is None or total_w == 0 else weights[c] * s / total_w
        if contrib is not None:
            score += contrib
        terms[c] = {"score": None if s is None else round(s, 4), "weight": weights[c],
                    "contribution": None if contrib is None else round(contrib, 4), "note": note}

    in_scope = all(v in ("met", "n/a") for v in status.values())
    relevant = directness != "not_relevant" and score >= cfg.min_relevant_score
    if agree is None:  # nothing but semantic similarity links this evidence to the question
        relevant = relevant and ev.semantic is not None and ev.semantic >= cfg.min_semantic_no_entity
    role = "excluded" if not relevant else (
        "supporting" if directness == "direct" and in_scope and score >= cfg.supported_score else "context")
    return ItemVerification(
        id=ev.id, score=round(score, 4), terms=terms, directness=directness, directness_reasons=dreasons, constraints=status,
        in_scope=in_scope, role=role, assertion_note=assertion_note if ev.assertion != "affirmed" else None,
        corroborating_ids=list(corroborating), conflict_ids=conflict_ids, claim_check=claim_check(ev, q) if agree == 1.0 else None)
