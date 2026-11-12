"""Deterministic, offline answer composer: the default provider (no language model, no network, no paid API).

It turns verified evidence into plain sentences with fixed templates. It can only say what the evidence items say:
every number and date in a sentence is copied from an evidence field, and every sentence cites its evidence ids. It
reports what the documents state ("X is documented ...") and never diagnoses, recommends or interprets.
"""

from evidence_qa.types import (
    CHANGE,
    CHECK,
    CONFLICT,
    CO_MENTION,
    FACT,
    AnswerContext,
    Claim,
    CtxEvidence,
    Draft,
)

MAX_CLAIMS = 15


def value_with_unit(e: CtxEvidence) -> str:
    if e.value_text is None:
        return ""
    unit = e.unit_text if e.unit_text and e.unit_text.lower() not in e.value_text.lower() else ""
    return f"{e.value_comparator or ''}{e.value_text}{' ' + unit if unit else ''}"


def describe(e: CtxEvidence) -> str:
    """One sentence stating what this evidence item says."""
    when = f" on {e.date_iso}" if e.date_iso else ""
    if e.entity_type == "date":
        return f"The date {e.date_iso or e.date_text} is documented"
    if e.value_text is not None:
        if e.entity_type == "medication":
            return f"{e.entity_name} is documented at {value_with_unit(e)}{when}"
        return f"{e.entity_name} was {value_with_unit(e)}{when}"
    suffix = f" (dated {e.date_iso})" if e.date_iso else ""
    return {
        "affirmed": f"{e.entity_name} is documented{suffix}",
        "negated": f"{e.entity_name} is documented as absent (negated){suffix}",
        "uncertain": f"{e.entity_name} is documented with uncertainty (possible, not confirmed){suffix}",
        "family_history": f"A family history of {e.entity_name} is documented{suffix}",
        "allergy": f"An allergy to {e.entity_name} is documented{suffix}",
        "discontinued": f"{e.entity_name} is documented as discontinued{suffix}",
        "planned": f"{e.entity_name} is documented as planned (not yet current){suffix}",
    }.get(e.assertion, f"{e.entity_name} is documented{suffix}")


def _ordered(items: list[CtxEvidence]) -> list[CtxEvidence]:
    return sorted(items, key=lambda e: (e.entity_name, e.date_iso or "9999", e.document_filename, e.page_number, e.id))


def compose(ctx: AnswerContext) -> Draft:
    claims: list[Claim] = []
    caveats: list[str] = []
    seq = iter(range(1, 10_000))

    def add(text: str, ids: list[str], kind: str = FACT) -> Claim:
        c = Claim(f"c{next(seq)}", text.rstrip(".") + ".", ids, kind)
        claims.append(c)
        return c

    by_id = ctx.by_id()
    conflict_set = set(ctx.conflicting_ids)
    # Facts: every supporting item, plus (when the evidence conflicts) every item involved in the conflict.
    shown = list(ctx.supporting) + [by_id[i] for i in ctx.conflicting_ids if i in by_id and by_id[i] not in ctx.supporting]
    shown = _ordered(shown)

    if ctx.primary_type == "relationship" and ctx.state != "conflicting":
        a = [e for e in ctx.supporting if ctx.entities and e.entity_name.lower() == ctx.entities[0].lower()]
        b = [e for e in ctx.supporting if len(ctx.entities) > 1 and e.entity_name.lower() == ctx.entities[1].lower()]
        pair = next(((x, y) for x in a for y in b if x.document_filename == y.document_filename and x.page_number == y.page_number
                     and x.source_text == y.source_text), None)
        if pair:
            x, y = pair
            add(f'{x.entity_name} and {y.entity_name} are mentioned together in the same sentence: "{x.source_text}"', [x.id, y.id], CO_MENTION)
            caveats.append("The documents mention these together; the nature of any relationship between them is not interpreted here.")
            return Draft(claims, caveats)
        caveats.append("The two items were found, but not in the same sentence; no relationship is stated here.")

    grouped: dict[str, list[str]] = {}  # identical statements found in several places become ONE claim citing every source
    for e in shown:
        grouped.setdefault(describe(e), []).append(e.id)
    for text, ids in list(grouped.items())[:MAX_CLAIMS]:
        add(text, ids, FACT)
    if len(grouped) > MAX_CLAIMS:
        caveats.append(f"Only the first {MAX_CLAIMS} of {len(grouped)} distinct statements are listed.")

    sup_ids = {e.id for e in ctx.supporting}
    for p in ctx.conflicts:
        if p.category == "temporal_change" and p.in_scope and set(p.evidence_ids) <= sup_ids and p.direction in ("increased", "decreased", "unchanged"):
            a, b = by_id[p.evidence_ids[0]], by_id[p.evidence_ids[1]]
            add(f"Between {a.date_iso} and {b.date_iso}, {a.entity_name} changed from {value_with_unit(a)} to {value_with_unit(b)} "
                f"({p.direction}; a numeric comparison only, not a clinical judgement)", [a.id, b.id], CHANGE)

    for p in ctx.conflicts:
        if p.category != "possible_contradiction" or not p.in_scope or not (set(p.evidence_ids) <= set(by_id)):
            continue
        a, b = by_id[p.evidence_ids[0]], by_id[p.evidence_ids[1]]
        when = f" for {a.date_iso}" if a.date_iso and a.date_iso == b.date_iso else ""
        what = "differing statements" if a.value_text is None else "differing values"
        text = f"The documents contain {what} about {a.entity_name}{when}"
        if a.value_text is not None:
            text += f": {value_with_unit(a)} ({a.document_filename}, page {a.page_number}) and {value_with_unit(b)} ({b.document_filename}, page {b.page_number})"
        else:
            text += f": {a.assertion} ({a.document_filename}, page {a.page_number}) and {b.assertion} ({b.document_filename}, page {b.page_number})"
        add(text, [a.id, b.id], CONFLICT)
        if p.strength == "weak":
            caveats.append(f"For {a.entity_name}, at least one statement has no date, so it cannot be told whether this is a change over time or a contradiction.")
    if conflict_set:
        caveats.append("This system does not decide which conflicting statement is correct.")

    if ctx.claim_assessment:
        for e in ctx.supporting:
            if e.claim_check in ("confirms", "contradicts") and ctx.value_constraint_texts:
                cond = ctx.value_constraint_texts[0]
                verb = "satisfies" if e.claim_check == "confirms" else "does not satisfy"
                add(f"The documented value ({value_with_unit(e)}{', ' + e.date_iso if e.date_iso else ''}) {verb} the condition stated in the question ({cond})",
                    [e.id], CHECK)

    for code, text, kind in ctx.state_reasons:
        if kind == "limiting" and ctx.state == "partially_supported":
            caveats.append(text)
    if any(e.modality in ("ocr", "image_ocr") for e in shown):
        caveats.append("At least one cited item comes from OCR and may contain recognition errors.")
    return Draft(claims, caveats, acknowledges_conflict=bool(conflict_set))


def context_notes(ctx: AnswerContext, limit: int = 5) -> list[Claim]:
    """Related evidence shown next to an abstention: grounded, cited, and explicitly not an answer."""
    out = []
    for n, e in enumerate(_ordered(ctx.context)[:limit], start=1):
        out.append(Claim(f"n{n}", describe(e) + ".", [e.id], "context"))
    return out
