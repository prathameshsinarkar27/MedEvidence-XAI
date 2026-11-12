"""Grounding guard: nothing a provider returns is shown unless it passes these checks.

Checks (all deterministic, all heuristic: they catch the common ways an answer leaves its evidence, not every possible error):
  - at least one claim; every claim cites at least one evidence id; every cited id is in the verified context
  - every number and date in a claim text appears in the cited evidence (its source text, value, date or entity name)
  - claims about negated / uncertain / family-history evidence carry the matching wording
  - no advice, recommendation, diagnosis or treatment wording unless that exact word is in the cited evidence
  - when the evidence state is "conflicting" the answer acknowledges the conflict
A draft with any violation is rejected and the deterministic extractive answer is used instead.
"""

import re

from evidence_qa.types import AnswerContext, Draft, Violation

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_ADVICE = re.compile(r"\b(should|must|recommend\w*|advis\w*|suggest\w*|diagnos\w*|prescrib\w*|treat(?:ment|ing|s|ed)?|cure[sd]?|therap\w*|"
                     r"consult|stop taking|start taking|increase the dose|decrease the dose)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(no|not|absent|negat\w*|denies|denied|without|none|never)\b", re.IGNORECASE)
_HEDGE = re.compile(r"\b(possible|possibly|uncertain\w*|may|might|suspect\w*|probable|probably|likely|unclear|query|not confirmed)\b", re.IGNORECASE)
_FAMILY = re.compile(r"\bfamily\b", re.IGNORECASE)
_CONFLICT_WORDS = re.compile(r"\b(conflict\w*|contradict\w*|differ\w*|disagree\w*|inconsisten\w*)\b", re.IGNORECASE)
MAX_CLAIM_CHARS = 400


def _numbers(text: str) -> set[float]:
    out = set()
    for token in _NUMBER.findall(text):
        try:
            out.add(float(token.replace(",", ".")))
        except ValueError:
            pass
    return out


_PAGE_REF = re.compile(r"\bpages?\s+(\d+)\b", re.IGNORECASE)


def _haystack(e) -> str:
    return " ".join(x for x in (e.source_text, e.mention_text, e.entity_name, e.value_text, e.date_iso, e.date_text, e.unit_text,
                                e.document_filename, f"page {e.page_number}") if x)


def validate(draft: Draft, ctx: AnswerContext) -> list[Violation]:
    out: list[Violation] = []
    known = ctx.by_id()
    allowed = {e.id for e in ctx.supporting} | set(ctx.conflicting_ids)
    if not draft.claims:
        return [Violation("no_claims", "The answer contains no claim.")]
    for c in draft.claims:
        if not c.evidence_ids:
            out.append(Violation("missing_evidence", "A claim cites no evidence.", c.id))
            continue
        bad = [i for i in c.evidence_ids if i not in allowed or i not in known]
        if bad:
            out.append(Violation("unknown_evidence", f"A claim cites evidence that is not in the verified context: {bad}.", c.id))
            continue
        cited = [known[i] for i in c.evidence_ids]
        hay = " ".join(_haystack(e) for e in cited)
        if len(c.text) > MAX_CLAIM_CHARS:
            out.append(Violation("claim_too_long", "A claim is longer than allowed.", c.id))
        extra = sorted(_numbers(c.text) - _numbers(hay))  # a 'page N' reference is checked as text above: only cited pages are in hay
        if extra:
            out.append(Violation("ungrounded_number", f"A claim states a number or date not found in its evidence: {extra}.", c.id))
        for word in {m.group(0).lower() for m in _ADVICE.finditer(c.text)}:
            if not re.search(rf"\b{re.escape(word)}", hay, re.IGNORECASE):
                out.append(Violation("advice_language", f"A claim uses advice, diagnosis or treatment wording ('{word}') that is not in the evidence.", c.id))
        if c.kind in ("fact", "context"):
            for e in cited:
                if e.assertion == "negated" and not _NEGATION.search(c.text):
                    out.append(Violation("assertion_mismatch", "The evidence is negated but the claim does not say so.", c.id))
                elif e.assertion == "uncertain" and not _HEDGE.search(c.text):
                    out.append(Violation("assertion_mismatch", "The evidence is uncertain but the claim states it as fact.", c.id))
                elif e.assertion == "family_history" and not _FAMILY.search(c.text):
                    out.append(Violation("assertion_mismatch", "The evidence is about family history but the claim does not say so.", c.id))
    if draft.provider != "extractive":  # caveats written by a model are untrusted too (this system's own templates are not)
        for text in draft.caveats:
            for word in {m.group(0).lower() for m in _ADVICE.finditer(text)}:
                out.append(Violation("advice_language", f"A caveat uses advice wording ('{word}')."))
    if ctx.state == "conflicting":
        all_text = " ".join([c.text for c in draft.claims] + draft.caveats)
        if not (draft.acknowledges_conflict and _CONFLICT_WORDS.search(all_text)):
            out.append(Violation("conflict_not_acknowledged", "The evidence conflicts, but the answer does not say so."))
    return out

