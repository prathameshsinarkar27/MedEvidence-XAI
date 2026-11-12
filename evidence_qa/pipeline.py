"""Verified evidence context -> explainable answer.

Order: abstention policy -> provider draft (extractive by default, optional LLM) -> grounding guard (on any violation the
deterministic extractive answer is used instead) -> citation markers -> confidence report. The provider only ever sees the
verified evidence context, never the raw documents or unverified candidates.
"""

from evidence_qa import extractive, guard
from evidence_qa.confidence import estimate
from evidence_qa.llm import ProviderError
from evidence_qa.types import (
    ABSTAINED,
    ABSTENTION_MESSAGE,
    ANSWERED,
    ANSWERED_WITH_CAVEATS,
    CONFLICT_REPORTED,
    AnswerContext,
    AnswerResult,
    Claim,
    Draft,
)


def _render(claims: list[Claim]) -> str:
    return " ".join(f"{c.text} [{n}]" for n, c in enumerate(claims, start=1))


def _abstain(ctx: AnswerContext, reason: str, warnings: list[str], provider_used: str = "extractive") -> AnswerResult:
    notes = extractive.context_notes(ctx) if ctx.state == "partially_supported" and not ctx.advice_request else []
    return AnswerResult(status=ABSTAINED, text=ABSTENTION_MESSAGE, claims=[], caveats=[], context_notes=notes,
                        confidence=estimate(ctx, [], ABSTAINED, provider_used), provider_used=provider_used, warnings=warnings,
                        abstention_reason=reason)


def build_answer(ctx: AnswerContext, provider=None) -> AnswerResult:
    """`provider` is None (extractive) or an object with `.generate(ctx) -> Draft` and `.name`."""
    warnings: list[str] = []
    if ctx.advice_request:
        return _abstain(ctx, "advice_request_out_of_scope", warnings)
    if ctx.state == "insufficient_evidence":
        return _abstain(ctx, "insufficient_evidence", warnings)
    if not ctx.supporting and not ctx.conflicting_ids:
        return _abstain(ctx, "no_supporting_evidence", warnings)

    reference = extractive.compose(ctx)
    draft, used, violations = reference, "extractive", []
    if provider is not None:
        try:
            candidate = provider.generate(ctx)
        except ProviderError as exc:
            warnings.append(f"llm_fallback:{exc.code}: {exc.message} The deterministic extractive answer is shown instead.")
        else:
            violations = guard.validate(candidate, ctx)
            if violations:
                warnings.append("llm_output_rejected: " + "; ".join(sorted({v.code for v in violations}))
                                + ". The deterministic extractive answer is shown instead.")
            else:
                draft, used, violations = candidate, provider.name, []
    own = guard.validate(draft, ctx) if used == "extractive" else []
    if own:  # a bug in the composer must never reach the user as an answer
        return _abstain(ctx, "internal_guard_failure", warnings + ["extractive_answer_failed_validation"], "extractive")

    status = CONFLICT_REPORTED if ctx.state == "conflicting" else ANSWERED_WITH_CAVEATS if ctx.state == "partially_supported" else ANSWERED
    claims = _renumber(draft)
    return AnswerResult(status=status, text=_render(claims), claims=claims, caveats=draft.caveats, context_notes=[],
                        confidence=estimate(ctx, claims, status, used), provider_used=used, warnings=warnings, violations=violations)


def _renumber(draft: Draft) -> list[Claim]:
    return [Claim(f"c{n}", c.text, c.evidence_ids, c.kind) for n, c in enumerate(draft.claims, start=1)]
