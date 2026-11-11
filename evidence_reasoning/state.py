"""Evidence state: can the retrieved, verified evidence support answering the question?

    supported              every question target has direct, in-scope, sufficiently scored evidence and nothing contradicts it
    partially_supported    some targets are covered, or evidence exists only indirectly / outside the question's constraints /
                           with a low score / hedged; or the entity could not be identified
    conflicting            in-scope evidence contains a possible contradiction (temporal changes are NOT conflicts)
    insufficient_evidence  no relevant evidence (or the question asks for advice, which documents cannot support)

The state describes the evidence, not the truth of any answer. Rules by question type (all documented in
docs/verification.md): comparison needs two dated time points for one entity; a relationship question is "supported" only
when both entities appear in the same source sentence (co-mention; the relationship itself is not interpreted).
"""

from evidence_reasoning.conflicts import ConflictAnalysis
from evidence_reasoning.types import (
    CONFLICTING,
    INSUFFICIENT,
    PARTIAL,
    POSSIBLE_CONTRADICTION,
    Q_COMPARISON,
    Q_RELATIONSHIP,
    SUPPORTED,
    EvidenceState,
    ItemVerification,
    QuestionAnalysis,
    ReasoningConfig,
    Reason,
    VEvidence,
)
from hybrid_retrieval import entity_score

_REASON_TEXT = {
    "entity_only_partially_matches": "the evidence entity only partly matches the question entity",
    "assertion_does_not_fit_question": "the statement is about something other than the patient's own current finding",
    "no_value_stated": "the evidence names the entity but states no value",
    "other_page": "it is on a different page than the one asked about",
    "outside_period": "it is dated outside the requested period",
    "date_unknown": "its date is unknown, so the requested period cannot be confirmed",
    "recency_cannot_be_established": "latest/earliest cannot be established without a date",
    "entity_not_identified": "no entity was identified in the question",
}


def _matches(ev: VEvidence, target: str, by: str) -> bool:
    return ev.entity_type == target if by == "type" else entity_score(ev.entity_name, [target]) > 0


def _same_sentence(a: VEvidence, b: VEvidence) -> bool:
    if a.document_id != b.document_id or a.page_number != b.page_number:
        return False
    if None not in (a.source_start, a.source_end, b.source_start, b.source_end):
        return (a.source_start, a.source_end) == (b.source_start, b.source_end)
    return bool(a.source_text) and a.source_text == b.source_text


def decide(q: QuestionAnalysis, items: list[ItemVerification], evs: dict[str, VEvidence], conflicts: ConflictAnalysis,
           cfg: ReasoningConfig, retrieved: int) -> EvidenceState:
    supporting = [i for i in items if i.role == "supporting"]
    context = [i for i in items if i.role == "context"]
    relevant = supporting + context
    ids = lambda xs: [i.id for i in xs]  # noqa: E731

    if q.advice_request:
        return EvidenceState(INSUFFICIENT, [Reason(
            "advice_request_out_of_scope", "The question asks for advice, a recommendation, a diagnosis or a prediction. Documents "
            "can only be checked for what they state; this system does not give medical advice.", "decisive")], [], ids(relevant), [], {})
    if not relevant:
        return EvidenceState(INSUFFICIENT, [Reason(
            "no_relevant_evidence", f"{retrieved} evidence item(s) were retrieved and none passed entity agreement and the minimum "
            f"evidence score ({cfg.min_relevant_score}).", "decisive")], [], [], [], {})

    by, targets = ("entity", q.entities) if q.entities else ("type", q.requested_entity_types)
    reasons: list[Reason] = []
    coverage: dict[str, str] = {}
    for t in targets:
        sup_t = [i for i in supporting if _matches(evs[i.id], t, by)]
        if sup_t and all(evs[i.id].assertion == "uncertain" for i in sup_t):
            coverage[t] = "partial"
            reasons.append(Reason("only_hedged_evidence", f"All direct evidence for {t} states it with uncertainty (hedged).", "limiting"))
        elif sup_t:
            coverage[t] = "covered"
        elif any(_matches(evs[i.id], t, by) for i in relevant):
            coverage[t] = "partial"
            reasons.append(_why_not_covered(t, [i for i in relevant if _matches(evs[i.id], t, by)], evs, cfg))
        else:
            coverage[t] = "missing"
            reasons.append(Reason("no_evidence_for_entity", f"No relevant evidence was found for {t}.", "limiting"))

    state = _base_state(q, targets, by, coverage, supporting, relevant, evs, reasons)

    rel_ids = {i.id for i in relevant}
    in_scope_conflicts = [p for p in conflicts.pairs if p.category == POSSIBLE_CONTRADICTION and p.in_scope
                          and set(p.evidence_ids) <= rel_ids]
    conflicting_ids = sorted({i for p in in_scope_conflicts for i in p.evidence_ids})
    if in_scope_conflicts and state != INSUFFICIENT:
        state = CONFLICTING
        for p in in_scope_conflicts[:5]:
            reasons.append(Reason("possible_contradiction", f"{p.entity_name}: {p.explanation}"
                                  + (" [weak: time unknown]" if p.strength == "weak" else ""), "decisive"))
    reasons += _info_reasons(q, supporting, conflicts, evs)

    if state == SUPPORTED:
        reasons.insert(0, Reason("sufficient_direct_evidence", "Every question target has direct, in-scope evidence scoring at least "
                                 f"{cfg.supported_score}, and no in-scope contradiction was found.", "decisive"))
    elif state == PARTIAL and not any(r.kind in ("limiting", "decisive") for r in reasons):
        reasons.insert(0, Reason("partial_evidence", "Evidence exists but does not fully cover the question.", "limiting"))

    claim = None
    checks = [i.claim_check for i in supporting if i.claim_check]
    if q.value_constraints and checks:
        claim = ("confirmed" if set(checks) == {"confirms"} else "contradicted" if set(checks) == {"contradicts"}
                 else "mixed" if {"confirms", "contradicts"} <= set(checks) else "undetermined")
    return EvidenceState(state, reasons, ids(supporting), ids(context), conflicting_ids, coverage, claim)


def _why_not_covered(target: str, rel: list[ItemVerification], evs: dict[str, VEvidence], cfg: ReasoningConfig) -> Reason:
    out_of_scope = [i for i in rel if not i.in_scope]
    if out_of_scope and all(not i.in_scope for i in rel):
        dates = sorted({evs[i.id].date_iso or "undated" for i in out_of_scope})
        return Reason("found_outside_constraints", f"Evidence for {target} exists, but not for what the question restricts "
                      f"(period, page or latest/earliest). Dates available: {', '.join(dates)}.", "limiting")
    codes = [c for i in rel for c in i.directness_reasons]
    if codes:
        top = max(set(codes), key=codes.count)
        return Reason("only_indirect_evidence", f"Evidence for {target} is only indirect: {_REASON_TEXT.get(top, top)}.", "limiting")
    best = max(i.score for i in rel)
    return Reason("low_evidence_score", f"The best evidence score for {target} is {best:.2f}, below the {cfg.supported_score} needed.", "limiting")


def _base_state(q, targets, by, coverage, supporting, relevant, evs, reasons) -> str:
    if not targets:
        reasons.append(Reason("entity_not_identified", "No entity was identified in the question, so entity agreement cannot be "
                              "checked; the state is capped at partially supported.", "limiting"))
        return PARTIAL
    covered = [t for t in targets if coverage[t] == "covered"]
    if q.primary == Q_COMPARISON and len(targets) == 1 and covered:
        points = {evs[i.id].date_iso for i in supporting if evs[i.id].date_iso and _matches(evs[i.id], targets[0], by)}
        reasons.append(Reason("comparison_points", f"{len(points)} dated time point(s) available for {targets[0]}.", "info"))
        if len(points) >= 2:
            return SUPPORTED
        reasons.append(Reason("comparison_needs_two_time_points", "A comparison needs at least two dated values of the same entity.", "limiting"))
        return PARTIAL
    if q.primary == Q_RELATIONSHIP:
        if len(targets) < 2:
            reasons.append(Reason("relationship_needs_two_entities", "A relationship question needs two recognised entities.", "limiting"))
            return PARTIAL if any(coverage[t] != "missing" for t in targets) else INSUFFICIENT
        if len(covered) == len(targets):
            a = [evs[i.id] for i in supporting if _matches(evs[i.id], targets[0], by)]
            b = [evs[i.id] for i in supporting if _matches(evs[i.id], targets[1], by)]
            if any(_same_sentence(x, y) for x in a for y in b):
                reasons.append(Reason("co_mentioned_same_sentence", "Both entities appear in the same source sentence or table row. "
                                      "Only the co-mention is established; the relationship itself is not interpreted.", "info"))
                return SUPPORTED
            same_page = any(x.document_id == y.document_id and x.page_number == y.page_number for x in a for y in b)
            reasons.append(Reason("co_mentioned_same_page_only" if same_page else "entities_not_co_mentioned",
                                  "Both entities have evidence, but not in the same sentence" + (" (same page)." if same_page else "."), "limiting"))
            return PARTIAL
    if len(covered) == len(targets):
        return SUPPORTED
    return PARTIAL if any(coverage[t] != "missing" for t in targets) else INSUFFICIENT


def _info_reasons(q, supporting, conflicts: ConflictAnalysis, evs) -> list[Reason]:
    out: list[Reason] = []
    sup_ids = {i.id for i in supporting}
    if not (q.periods or q.recency) and q.primary != Q_COMPARISON:
        for name, points in conflicts.timelines.items():
            dates = sorted({p["date"] for p in points if set(p["evidence_ids"]) & sup_ids})
            if len(dates) >= 2:
                out.append(Reason("multiple_times_no_period", f"{name} has evidence on {len(dates)} dates ({', '.join(dates)}); the "
                                  "question does not say which one it means.", "info"))
    if conflicts.counts.get("temporal_change"):
        out.append(Reason("temporal_changes_present", f"{conflicts.counts['temporal_change']} temporal change(s) between dated values "
                          "were found; these are changes over time, not contradictions.", "info"))
    if conflicts.counts.get("measurement_variation"):
        out.append(Reason("measurement_variation_present", f"{conflicts.counts['measurement_variation']} small difference(s) within "
                          "the tolerance were found (measurement variation).", "info"))
    return out
