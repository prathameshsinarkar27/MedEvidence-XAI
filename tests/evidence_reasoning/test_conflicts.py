"""Conflict detection: temporal change vs measurement variation vs possible contradiction (and what is NOT a conflict)."""

from evidence_reasoning import ReasoningConfig, analyze_conflicts

from tests.evidence_reasoning.helpers import bp, ev, finding


def cats(r):
    return sorted((p.category, p.reason) for p in r.pairs)


def test_different_dates_are_a_temporal_change_not_a_contradiction():
    a, b = ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12")
    r = analyze_conflicts([b, a])
    assert cats(r) == [("temporal_change", "different_dates")]
    p = r.pairs[0]
    assert p.evidence_ids == (a.id, b.id) and p.details["direction"] == "decreased" and p.details["gap_days"] == 101
    assert p.details["value_a"] == "8.2" and p.details["value_b"] == "7.8" and r.counts["possible_contradiction"] == 0


def test_large_difference_across_dates_is_still_only_a_change():
    r = analyze_conflicts([bp(120, 80, "2026-05-03"), bp(190, 120, "2026-08-12")])
    assert cats(r) == [("temporal_change", "different_dates")]


def test_same_day_small_difference_is_measurement_variation():
    r = analyze_conflicts([bp(120, 80), bp(122, 80)])
    assert cats(r) == [("measurement_variation", "within_tolerance")]
    assert r.pairs[0].details["relative_difference"] <= 0.10


def test_same_day_large_difference_is_a_possible_contradiction():
    r = analyze_conflicts([bp(120, 80), bp(150, 95)])
    assert cats(r) == [("possible_contradiction", "values_differ_same_date")]
    assert r.pairs[0].strength == "moderate" and "12" in r.pairs[0].explanation


def test_tolerances_are_configurable_per_entity_type():
    labs = [ev(value="7.8"), ev(value="8.0")]  # 2.5 % apart
    assert cats(analyze_conflicts(labs)) == [("measurement_variation", "within_tolerance")]
    assert cats(analyze_conflicts(labs, ReasoningConfig(tolerance_lab=0.01))) == [("possible_contradiction", "values_differ_same_date")]
    meds = [ev("Metformin", "500", etype="medication", unit="mg"), ev("Metformin", "1000", etype="medication", unit="mg")]
    assert cats(analyze_conflicts(meds)) == [("possible_contradiction", "values_differ_same_date")]


def test_same_finding_is_agreement_and_corroboration():
    a, b = ev(value="7.8"), ev(value="7.8", doc="d2")
    r = analyze_conflicts([a, b])
    assert r.pairs == [] and r.agreements[a.id] == [b.id] and r.agreements[b.id] == [a.id]


def test_undated_difference_is_a_weak_possible_contradiction():
    r = analyze_conflicts([ev(value="8.2", date="2026-05-03"), ev(value="7.0", date=None)])
    assert cats(r) == [("possible_contradiction", "values_differ_time_unknown")] and r.pairs[0].strength == "weak"


def test_undated_twin_of_a_dated_value_creates_no_pair():
    old, new, twin = ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12"), ev(value="7.8", date=None)
    r = analyze_conflicts([old, new, twin])
    assert cats(r) == [("temporal_change", "different_dates")]


def test_unit_mismatch_comparators_and_text_values_are_not_compared():
    r = analyze_conflicts([ev(value="7.8", unit="%"), ev(value="62", unit="mmol/mol")])
    assert r.pairs == [] and r.skipped[0]["reason"] == "unit_mismatch"
    a, b = ev(value="5.0"), ev(value="6.0")
    object.__setattr__(a, "value_comparator", "<")
    r = analyze_conflicts([a, b])
    assert r.pairs == [] and r.skipped[0]["reason"] == "values_not_comparable"


def test_opposite_assertions_same_date_conflict_but_different_dates_change():
    sym = lambda a, d: finding("Chest pain", "symptom", a, d)  # noqa: E731
    r = analyze_conflicts([sym("affirmed", "2026-05-03"), sym("negated", "2026-08-12")])
    assert cats(r) == [("temporal_change", "assertion_changed_over_time")]
    r = analyze_conflicts([sym("affirmed", "2026-08-12"), sym("negated", "2026-08-12")])
    assert cats(r) == [("possible_contradiction", "opposite_assertions_same_date")]
    r = analyze_conflicts([sym("affirmed", None), sym("negated", None)])
    assert cats(r) == [("possible_contradiction", "opposite_assertions_time_unknown")] and r.pairs[0].strength == "weak"


def test_unrelated_assertions_and_same_statement_repeated_are_not_conflicts():
    r = analyze_conflicts([finding("Diabetes mellitus", assertion="affirmed"), finding("Diabetes mellitus", assertion="family_history")])
    assert r.pairs == [] and r.skipped[0]["reason"] == "assertions_not_comparable"
    r = analyze_conflicts([finding("Diabetes mellitus", date="2026-05-03"), finding("Diabetes mellitus", date="2026-08-12")])
    assert r.pairs == [] and r.skipped == []


def test_only_the_same_entity_is_compared():
    r = analyze_conflicts([ev("Potassium", "4.1", unit="mmol/L"), ev("Sodium", "140", unit="mmol/L")])
    assert r.pairs == [] and r.skipped == []


def test_timelines_list_dated_values_in_time_order():
    r = analyze_conflicts([ev(value="7.8", date="2026-08-12"), ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12", doc="d2")])
    tl = r.timelines["Hemoglobin A1c"]
    assert [p["date"] for p in tl] == ["2026-05-03", "2026-08-12"] and len(tl[1]["evidence_ids"]) == 2
    assert analyze_conflicts([ev(value="7.8")]).timelines == {}


def test_deterministic_regardless_of_input_order():
    items = [ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12"), bp(120, 80), bp(150, 95)]
    forward = [(p.evidence_ids, p.category) for p in analyze_conflicts(items).pairs]
    backward = [(p.evidence_ids, p.category) for p in analyze_conflicts(items[::-1]).pairs]
    assert sorted(forward) == sorted(backward)
