"""Confidence report: three different things, kept apart and never presented as medical certainty.

model_confidence     how sure a language model is. Not available: the extractive provider uses no model, and an LLM's
                     self-reported confidence is not calibrated, so none is reported.
evidence_confidence  weakest-link heuristic over the evidence the answer cites: the minimum Phase 8 evidence score of the
                     cited items (plus the minimum and mean extraction confidence). Not a probability.
answer_support       how fully the evidence covers the question: the evidence state, coverage, and how many claims are cited.
"""

from evidence_qa.types import ABSTAINED, AnswerContext, Claim, ConfidenceReport

NOTE = "Heuristic indicators of how well the documents support the answer. They are not probabilities and not medical certainty."


def estimate(ctx: AnswerContext, claims: list[Claim], status: str, provider_used: str) -> ConfidenceReport:
    cited = {i for c in claims for i in c.evidence_ids}
    items = [e for e in ctx.by_id().values() if e.id in cited]
    model = {"available": False, "value": None,
             "note": ("No language model was used (deterministic extractive answer)." if provider_used == "extractive" else
                      "A language model wrote the draft; it reports no calibrated confidence, so none is shown.")}
    if status == ABSTAINED or not items:
        evidence = {"score": None, "min_extraction_confidence": None, "mean_extraction_confidence": None, "cited_items": 0,
                    "basis": "no evidence is cited", "note": NOTE}
    else:
        conf = [e.extraction_confidence for e in items]
        evidence = {"score": round(min(e.evidence_score for e in items), 3), "min_extraction_confidence": round(min(conf), 3),
                    "mean_extraction_confidence": round(sum(conf) / len(conf), 3), "cited_items": len(items),
                    "basis": "minimum Phase 8 evidence score over the cited evidence (weakest link)", "note": NOTE}
    label = {"supported": "full", "partially_supported": "partial", "conflicting": "conflicting",
             "insufficient_evidence": "none"}[ctx.state]
    support = {"state": ctx.state, "label": label, "claims": len(claims), "claims_with_evidence": sum(1 for c in claims if c.evidence_ids),
               "supporting_items": len(ctx.supporting), "conflicting_items": len(ctx.conflicting_ids), "coverage": dict(ctx.coverage),
               "note": "How much of the question the evidence covers; 'full' does not mean the evidence is clinically correct."}
    return ConfidenceReport(model, evidence, support)
