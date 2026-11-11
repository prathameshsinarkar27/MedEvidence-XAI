"""Evidence states for question -> evidence scenarios: supported / partially supported / conflicting / insufficient."""

import pytest

from evidence_reasoning import ReasoningConfig, understand_question, verify_question
from tests.evidence_reasoning.helpers import bp, ev, finding


def state(question, evidence, cfg=None):
    r = verify_question(understand_question(question), evidence, cfg)
    return r.state.state, {x.code for x in r.state.reasons}, r


MAY, AUG = ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12")


def test_supported_with_direct_in_scope_evidence():
    s, codes, r = state("What is the HbA1c on 12-Aug-2026?", [MAY, AUG])
    assert s == "supported" and "sufficient_direct_evidence" in codes
    assert r.state.supporting_ids == [AUG.id] and r.state.coverage == {"Hemoglobin A1c": "covered"} and r.state.conflicting_ids == []


def test_latest_selects_the_most_recent_value_and_a_temporal_change_is_not_a_conflict():
    s, codes, r = state("What is the latest HbA1c?", [MAY, AUG])
    assert s == "supported" and r.state.supporting_ids == [AUG.id] and "temporal_changes_present" in codes
    assert r.state.context_ids == [MAY.id] and r.state.conflicting_ids == []


def test_no_time_constraint_with_several_dates_is_supported_but_says_so():
    s, codes, _ = state("What is the HbA1c?", [MAY, AUG])
    assert s == "supported" and "multiple_times_no_period" in codes


def test_evidence_outside_the_requested_period_is_only_partial():
    s, codes, r = state("What was the HbA1c in June 2026?", [MAY, AUG])
    assert s == "partially_supported" and "found_outside_constraints" in codes and r.state.supporting_ids == []
    assert r.state.coverage == {"Hemoglobin A1c": "partial"}
    assert any("2026-05-03" in x.text for x in r.state.reasons)


def test_undated_evidence_cannot_confirm_a_requested_period_or_recency():
    assert state("HbA1c in May 2026", [ev(date=None)])[0] == "partially_supported"
    assert state("latest HbA1c", [ev(date=None)])[0] == "partially_supported"


def test_same_day_different_blood_pressure_is_conflicting():
    s, codes, r = state("What is the blood pressure on 12-Aug-2026?", [bp(120, 80), bp(150, 95)])
    assert s == "conflicting" and "possible_contradiction" in codes
    assert len(r.state.conflicting_ids) == 2 and r.conflicts.counts["possible_contradiction"] == 1


def test_blood_pressure_on_different_dates_is_not_a_conflict():
    s, _, r = state("What is the blood pressure?", [bp(120, 80, "2026-05-03"), bp(150, 95, "2026-08-12")])
    assert s == "supported" and r.conflicts.counts == {"temporal_change": 1, "measurement_variation": 0, "possible_contradiction": 0}


def test_a_contradiction_outside_the_question_scope_does_not_make_it_conflicting():
    items = [bp(120, 80, "2026-05-03"), bp(150, 95, "2026-05-03"), bp(130, 85, "2026-08-12")]
    s, _, r = state("What is the blood pressure on 12-Aug-2026?", items)
    assert s == "supported" and r.conflicts.counts["possible_contradiction"] == 1
    contradictions = [p for p in r.conflicts.pairs if p.category == "possible_contradiction"]
    assert contradictions and all(not p.in_scope for p in contradictions) and r.state.conflicting_ids == []


def test_measurement_variation_is_reported_but_not_a_conflict():
    s, codes, _ = state("What is the blood pressure on 12-Aug-2026?", [bp(120, 80), bp(122, 80)])
    assert s == "supported" and "measurement_variation_present" in codes


def test_opposite_assertions_without_dates_are_conflicting():
    s, _, _ = state("Does the patient have chest pain?", [finding("Chest pain", "symptom", "affirmed"), finding("Chest pain", "symptom", "negated")])
    assert s == "conflicting"
    s, codes, _ = state("Does the patient have chest pain?", [finding("Chest pain", "symptom", "affirmed", "2026-05-03"),
                                                              finding("Chest pain", "symptom", "negated", "2026-08-12")])
    assert s == "supported" and "temporal_changes_present" in codes


def test_negated_evidence_directly_answers_a_presence_question():
    s, _, r = state("Does the patient have chest pain?", [finding("Chest pain", "symptom", "negated")])
    assert s == "supported" and r.items[0].assertion_note


def test_hedged_evidence_is_only_partial():
    s, codes, _ = state("Does the patient have pneumonia?", [finding("Pneumonia", "condition", "uncertain")])
    assert s == "partially_supported" and "only_hedged_evidence" in codes


def test_family_history_does_not_support_a_question_about_the_patient():
    s, codes, _ = state("Does the patient have diabetes?", [finding("Diabetes mellitus", assertion="family_history")])
    assert s == "partially_supported" and "only_indirect_evidence" in codes


def test_no_evidence_for_the_entity_is_insufficient():
    s, codes, r = state("What is the sodium level?", [ev("Potassium", "4.1", unit="mmol/L"), ev()])
    assert s == "insufficient_evidence" and "no_relevant_evidence" in codes and r.state.supporting_ids == []
    assert state("What is the HbA1c?", [])[0] == "insufficient_evidence"


def test_two_entities_one_missing_is_partial():
    s, codes, r = state("What are the HbA1c and sodium?", [AUG])
    assert s == "partially_supported" and r.state.coverage == {"Hemoglobin A1c": "covered", "Sodium": "missing"}
    assert "no_evidence_for_entity" in codes


def test_value_requested_but_evidence_states_none_is_partial():
    s, codes, _ = state("What is the HbA1c value?", [ev(value=None, numeric=None)])
    assert s == "partially_supported" and "only_indirect_evidence" in codes


def test_low_score_evidence_is_partial_and_the_threshold_is_configuration():
    weak = ev(conf=0.4, sem=0.05, modality="ocr", ocr_confidence=45)
    s, codes, _ = state("What is the HbA1c?", [weak], ReasoningConfig(supported_score=0.95))
    assert s == "partially_supported" and "low_evidence_score" in codes
    assert state("What is the HbA1c?", [ev()])[0] == "supported"


def test_advice_requests_are_insufficient_whatever_the_evidence():
    s, codes, r = state("Should I stop metformin?", [ev("Metformin", "500", unit="mg", etype="medication")])
    assert s == "insufficient_evidence" and codes == {"advice_request_out_of_scope"} and r.state.supporting_ids == []


def test_unidentified_entity_caps_at_partial():
    s, codes, _ = state("blood thinner", [ev(sem=0.8)])
    assert s == "partially_supported" and "entity_not_identified" in codes
    assert state("blood thinner", [ev(sem=0.05)])[0] == "insufficient_evidence"


def test_comparison_needs_two_dated_points_of_one_entity():
    assert state("Compare HbA1c in May 2026 and August 2026", [MAY, AUG])[0] == "supported"
    s, codes, _ = state("Compare HbA1c over time", [AUG])
    assert s == "partially_supported" and "comparison_needs_two_time_points" in codes
    s, codes, _ = state("Compare HbA1c over time", [ev(value="8.2", date=None), ev(value="7.8", date=None)])
    assert s == "partially_supported"
    assert state("Compare HbA1c over time", [MAY, ev(value="7.9", date="2026-05-03")])[0] == "partially_supported"


def test_relationship_is_supported_only_by_a_co_mention_in_one_sentence():
    met = ev("Metformin", "500", None, etype="medication", unit="mg", text="Metformin 500 mg for diabetes.", start=0, end=30)
    dm = finding("Diabetes mellitus", text="Metformin 500 mg for diabetes.", start=0, end=30)
    s, codes, _ = state("Is metformin prescribed for diabetes?", [met, dm])
    assert s == "supported" and "co_mentioned_same_sentence" in codes
    dm2 = finding("Diabetes mellitus", text="History of diabetes.", start=40, end=60)
    s, codes, _ = state("Is metformin prescribed for diabetes?", [met, dm2])
    assert s == "partially_supported" and "co_mentioned_same_page_only" in codes
    other_doc = finding("Diabetes mellitus", doc="d2", text="Diabetes.")
    s, codes, _ = state("Is metformin prescribed for diabetes?", [met, other_doc])
    assert s == "partially_supported" and "entities_not_co_mentioned" in codes
    assert state("Why is metformin used?", [met])[0] == "partially_supported"


def test_list_questions_cover_the_requested_type():
    meds = [ev("Metformin", "500", None, etype="medication", unit="mg"), ev("Atorvastatin", "20", None, etype="medication", unit="mg")]
    s, _, r = state("List all medications", meds)
    assert s == "supported" and r.state.coverage == {"medication": "covered"} and len(r.state.supporting_ids) == 2
    assert state("List all medications", [ev()])[0] == "insufficient_evidence"
    assert state("What symptoms are mentioned?", [finding("Fever", "symptom")])[0] == "supported"


def test_claim_assessment_for_questions_that_state_a_value():
    assert state("Was HbA1c above 7 %?", [AUG])[2].state.claim_assessment == "confirmed"
    assert state("Was HbA1c above 9 %?", [AUG])[2].state.claim_assessment == "contradicted"
    assert state("Was HbA1c above 8 %?", [MAY, AUG])[2].state.claim_assessment == "mixed"
    assert state("What is the HbA1c?", [AUG])[2].state.claim_assessment is None


def test_deterministic_and_input_order_independent():
    a = verify_question(understand_question("What is the HbA1c?"), [MAY, AUG])
    b = verify_question(understand_question("What is the HbA1c?"), [AUG, MAY])
    assert a.state.state == b.state.state and sorted(a.state.supporting_ids) == sorted(b.state.supporting_ids)
    assert {i.id: i.score for i in a.items} == {i.id: i.score for i in b.items}


@pytest.mark.parametrize("q", ["What is the HbA1c?", "latest HbA1c", "Compare HbA1c", "blood thinner", "Should I stop metformin?"])
def test_state_is_always_one_of_four_and_never_an_answer(q):
    r = verify_question(understand_question(q), [MAY, AUG])
    assert r.state.state in {"supported", "partially_supported", "conflicting", "insufficient_evidence"}
    assert all(set(vars(x)) == {"code", "text", "kind"} for x in r.state.reasons)
