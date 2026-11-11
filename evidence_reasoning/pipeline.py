"""Question + retrieved evidence -> per-item verification, conflict analysis and an evidence state."""

from evidence_reasoning.conflicts import analyze_conflicts
from evidence_reasoning.state import decide
from evidence_reasoning.types import QuestionAnalysis, ReasoningConfig, VEvidence, VerificationResult
from evidence_reasoning.verification import entity_agreement, recency_targets, verify_item


def verify_question(q: QuestionAnalysis, evidence: list[VEvidence], cfg: ReasoningConfig | None = None) -> VerificationResult:
    cfg = cfg or ReasoningConfig()
    evs = {e.id: e for e in evidence}
    targets = recency_targets(evidence, q)
    entity_related = [e for e in evidence if (entity_agreement(e, q) or 0) > 0]
    conflicts = analyze_conflicts(entity_related, cfg)
    items = [verify_item(e, q, targets, conflicts, cfg) for e in sorted(evidence, key=lambda x: (x.retrieval_rank, x.order, x.id))]
    by_id = {i.id: i for i in items}
    for pair in conflicts.pairs:  # a pair matters for the state only if both items satisfy the question's constraints
        pair.in_scope = all(by_id[i].in_scope and by_id[i].role != "excluded" for i in pair.evidence_ids)
    return VerificationResult(items=items, conflicts=conflicts, state=decide(q, items, evs, conflicts, cfg, len(evidence)))
