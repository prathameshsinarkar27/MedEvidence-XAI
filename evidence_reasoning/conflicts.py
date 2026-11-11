"""Conflict detection between evidence items about the same entity.

A different value is NOT automatically a contradiction. For every pair of items about the same canonical entity:

* same finding (same assertion, same value and unit)           -> agreement (no conflict; counted as corroboration)
* both dated, on different dates                                -> TEMPORAL CHANGE (values legitimately change over time)
* same date (or unknown time), values differ by <= tolerance    -> MEASUREMENT VARIATION
* same date, values differ by more than the tolerance           -> POSSIBLE CONTRADICTION (moderate)
* one or both undated, values differ by more than the tolerance -> POSSIBLE CONTRADICTION (weak: the time is unknown)
* same date, opposite assertion (present vs absent)             -> POSSIBLE CONTRADICTION; on different dates: temporal change
* different units, comparators ("<5"), non-numeric values       -> not compared (listed in `skipped`); units are never converted

Tolerances are relative and configurable per entity type. They are engineering defaults, not clinical thresholds, and
they have not been validated ("Not yet evaluated."). The analysis reports numeric facts (direction, difference, days
between); it never says whether a change is good or bad.
"""

from datetime import date

from evidence_reasoning.types import (
    MEASUREMENT_VARIATION,
    POSSIBLE_CONTRADICTION,
    TEMPORAL_CHANGE,
    ConflictAnalysis,
    ConflictPair,
    ReasoningConfig,
    VEvidence,
)

_STATUS_PAIRS = ({"affirmed", "negated"}, {"affirmed", "discontinued"})


def _is_valued(e: VEvidence) -> bool:
    return e.value_text is not None


def _values(e: VEvidence) -> tuple[float, ...] | None:
    """Comparable numbers: (systolic, diastolic) for blood pressure, (value,) otherwise; None if not comparable."""
    sys_, dia = e.attributes.get("systolic"), e.attributes.get("diastolic")
    if sys_ is not None and dia is not None:
        return float(sys_), float(dia)
    if e.value_numeric is None or e.value_comparator:
        return None
    return (float(e.value_numeric),)


def _same_finding(a: VEvidence, b: VEvidence) -> bool:
    if a.assertion != b.assertion:
        return False
    if not (_is_valued(a) or _is_valued(b)):
        return True  # conditions / symptoms: the same statement, whatever the date
    va, vb = _values(a), _values(b)
    same_value = (va == vb) if va is not None and vb is not None else (a.value_text == b.value_text)
    if not same_value or a.unit_normalized != b.unit_normalized:
        return False
    return a.date_iso == b.date_iso or a.date_iso is None or b.date_iso is None


def _rel_diff(x: float, y: float) -> float:
    top = max(abs(x), abs(y))
    return 0.0 if top == 0 else abs(x - y) / top


def _days(d1: str, d2: str) -> int:
    return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days)


def _label(e: VEvidence) -> str:
    return f"{e.value_text}{' ' + e.unit_normalized if e.unit_normalized else ''}" if _is_valued(e) else e.assertion


def _pair(a: VEvidence, b: VEvidence, category: str, reason: str, text: str, strength: str = "moderate", **details) -> ConflictPair:
    return ConflictPair((a.id, b.id), a.entity_name, category, reason, text, strength, details)


def _compare(a: VEvidence, b: VEvidence, cfg: ReasoningConfig) -> ConflictPair | dict | None:
    """Classify one pair. Returns a ConflictPair, a skip record (dict) or None for agreement."""
    if _same_finding(a, b):
        return None
    dated = a.date_iso and b.date_iso
    same_day = dated and a.date_iso == b.date_iso
    earlier, later = (a, b) if (not dated or a.date_iso <= b.date_iso) else (b, a)
    base = {"date_a": a.date_iso, "date_b": b.date_iso, "gap_days": _days(a.date_iso, b.date_iso) if dated else None}

    if a.assertion != b.assertion:
        if {a.assertion, b.assertion} not in _STATUS_PAIRS:
            return {"evidence_ids": [a.id, b.id], "reason": "assertions_not_comparable",
                    "text": f"{a.assertion} and {b.assertion} are different kinds of statement and are not compared"}
        if dated and not same_day:
            return _pair(earlier, later, TEMPORAL_CHANGE, "assertion_changed_over_time",
                         f"{earlier.assertion} on {earlier.date_iso}, then {later.assertion} on {later.date_iso}",
                         earlier_assertion=earlier.assertion, later_assertion=later.assertion, **base)
        if same_day:
            return _pair(a, b, POSSIBLE_CONTRADICTION, "opposite_assertions_same_date",
                         f"{a.assertion} and {b.assertion} are both stated for {a.date_iso}", **base)
        return _pair(a, b, POSSIBLE_CONTRADICTION, "opposite_assertions_time_unknown",
                     f"{a.assertion} and {b.assertion} are stated and the date of at least one is unknown", "weak", **base)

    # same assertion, different findings: values differ
    if a.unit_normalized != b.unit_normalized:
        return {"evidence_ids": [a.id, b.id], "reason": "unit_mismatch",
                "text": f"units differ ({a.unit_normalized or 'none'} vs {b.unit_normalized or 'none'}); units are not converted"}
    va, vb = _values(a), _values(b)
    if va is None or vb is None or len(va) != len(vb):
        return {"evidence_ids": [a.id, b.id], "reason": "values_not_comparable",
                "text": f"'{a.value_text}' and '{b.value_text}' are not both plain numbers (comparator or text value)"}
    rel = max(_rel_diff(x, y) for x, y in zip(va, vb))
    tol = cfg.tolerance(a.entity_type)
    diff = {"value_a": a.value_text, "value_b": b.value_text, "unit": a.unit_normalized, "relative_difference": round(rel, 4),
            "tolerance": tol, **base}
    if dated and not same_day:
        ve, vl = _values(earlier), _values(later)
        direction = "increased" if sum(vl) > sum(ve) else "decreased" if sum(vl) < sum(ve) else "unchanged"
        return _pair(earlier, later, TEMPORAL_CHANGE, "different_dates",
                     f"{earlier.value_text} on {earlier.date_iso}, {later.value_text} on {later.date_iso} "
                     f"({direction}; {base['gap_days']} day(s) apart)", direction=direction,
                     **{**diff, "value_a": earlier.value_text, "value_b": later.value_text})
    when = f"on {a.date_iso}" if same_day else "(time of at least one value unknown)"
    if rel <= tol:
        return _pair(a, b, MEASUREMENT_VARIATION, "within_tolerance",
                     f"{_label(a)} and {_label(b)} {when}: relative difference {rel:.1%} is within the {tol:.0%} tolerance", **diff)
    if same_day:
        return _pair(a, b, POSSIBLE_CONTRADICTION, "values_differ_same_date",
                     f"{_label(a)} and {_label(b)} are both stated for {a.date_iso}: relative difference {rel:.1%} "
                     f"exceeds the {tol:.0%} tolerance", **diff)
    return _pair(a, b, POSSIBLE_CONTRADICTION, "values_differ_time_unknown",
                 f"{_label(a)} and {_label(b)} differ by {rel:.1%} (tolerance {tol:.0%}) and the date of at least one is unknown, "
                 "so the difference cannot be explained as a change over time", "weak", **diff)


def analyze_conflicts(evidence: list[VEvidence], cfg: ReasoningConfig | None = None) -> ConflictAnalysis:
    cfg = cfg or ReasoningConfig()
    groups: dict[tuple[str, str], list[VEvidence]] = {}
    for e in sorted(evidence, key=lambda x: (x.order, x.id)):
        groups.setdefault((e.entity_type, e.entity_name), []).append(e)

    pairs: list[ConflictPair] = []
    skipped: list[dict] = []
    agreements: dict[str, list[str]] = {e.id: [] for e in evidence}
    by_id = {e.id: e for e in evidence}
    for items in groups.values():
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                result = _compare(a, b, cfg)
                if result is None:
                    agreements[a.id].append(b.id)
                    agreements[b.id].append(a.id)
                elif isinstance(result, dict):
                    skipped.append({**result, "entity_name": a.entity_name})
                else:
                    pairs.append(result)

    # An undated item that repeats a dated item's finding is probably that same finding: do not let it create a
    # "time unknown" pair with something its dated twin was already (correctly) classified against.
    keyed = {frozenset(p.evidence_ids): p for p in pairs}
    drop: set[frozenset] = set()
    for p in pairs:
        if None not in (p.details.get("date_a"), p.details.get("date_b")):
            continue  # both dates known: the pair stands on its own
        for x, y in (p.evidence_ids, p.evidence_ids[::-1]):
            if by_id[x].date_iso is not None:
                continue
            for twin in agreements[x]:
                other = keyed.get(frozenset((twin, y))) if by_id[twin].date_iso else None
                if other is not None and None not in (other.details.get("date_a"), other.details.get("date_b")):
                    drop.add(frozenset(p.evidence_ids))
    pairs = [p for p in pairs if frozenset(p.evidence_ids) not in drop]

    timelines: dict[str, list[dict]] = {}
    for (etype, name), items in groups.items():
        if not any(_is_valued(e) for e in items):
            continue
        points: dict[tuple, dict] = {}
        for e in items:
            if e.date_iso and e.assertion == "affirmed":
                key = (e.date_iso, e.value_text, e.unit_normalized)
                points.setdefault(key, {"date": e.date_iso, "value": e.value_text, "unit": e.unit_normalized, "evidence_ids": []})
                points[key]["evidence_ids"].append(e.id)
        ordered = sorted(points.values(), key=lambda p: (p["date"], p["value"] or ""))
        if len({p["date"] for p in ordered}) >= 2:
            timelines[name] = ordered

    counts = {c: sum(1 for p in pairs if p.category == c) for c in (TEMPORAL_CHANGE, MEASUREMENT_VARIATION, POSSIBLE_CONTRADICTION)}
    return ConflictAnalysis(pairs=pairs, timelines=timelines, counts=counts, skipped=skipped, agreements=agreements)
