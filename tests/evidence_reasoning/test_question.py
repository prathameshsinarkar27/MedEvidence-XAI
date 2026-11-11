"""Question understanding: types, entities, dates, constraints, requested information, flags."""

import pytest

from evidence_reasoning import understand_question as u


@pytest.mark.parametrize("text,primary,types", [
    ("What was the latest HbA1c?", "value_lookup", {"value_lookup", "temporal"}),
    ("What is the HbA1c value?", "value_lookup", {"value_lookup"}),
    ("Compare HbA1c in May 2026 and August 2026", "comparison", {"comparison", "temporal"}),
    ("How did potassium change over time?", "comparison", {"comparison", "value_lookup"}),
    ("Does the patient have chest pain?", "entity_focused", {"entity_focused"}),
    ("List all medications", "summary", {"summary"}),
    ("Summarize the findings", "summary", {"summary"}),
    ("Is metformin prescribed for diabetes?", "relationship", {"relationship", "entity_focused"}),
    ("When was metformin started?", "temporal", {"temporal"}),
    ("What was the blood pressure on 12-Aug-2026?", "value_lookup", {"value_lookup", "temporal"}),
    ("blood thinner", "unclassified", {"unclassified"}),
])
def test_question_types(text, primary, types):
    a = u(text)
    assert a.primary == primary and set(a.types) == types
    for t in a.types:
        if t != "unclassified":
            assert a.cues[t], "every type records the words that triggered it"


def test_entities_synonyms_and_types():
    a = u("What is the blood sugar and the high blood pressure status?")
    assert a.entities == ["Glucose", "Hypertension"]
    assert a.entity_types == {"Glucose": "lab_result", "Hypertension": "condition"}
    assert u("HbA1c and metformin").entity_types == {"Hemoglobin A1c": "lab_result", "Metformin": "medication"}


def test_dates_periods_and_recency():
    a = u("HbA1c on 12-Aug-2026")
    assert a.periods == [("2026-08-12", "2026-08-12")] and a.recency is None
    assert u("potassium in May 2026").periods == [("2026-05-01", "2026-05-31")]
    assert u("earliest potassium").recency == "earliest" and u("latest potassium").recency == "latest"
    ambiguous = u("potassium on 03/04/2026")
    assert len(ambiguous.periods) == 2 and any("ambiguous" in n for n in ambiguous.notes)


def test_requested_information():
    assert "value" in u("What dose of metformin?").requested
    assert "date" in u("When was metformin started?").requested
    assert "presence" in u("Does the patient have chest pain?").requested
    assert "change" in u("Compare HbA1c in May and August 2026").requested
    assert "list" in u("List all medications").requested and u("List all medications").requested_entity_types == ["medication"]
    assert u("What symptoms are mentioned?").requested_entity_types == ["symptom"]
    assert u("Which lab results are there?").requested_entity_types == ["lab_result"]


def test_stated_values_become_constraints():
    c = u("Was HbA1c above 7 %?").value_constraints
    assert len(c) == 1 and (c[0].comparator, c[0].value, c[0].unit) == (">", 7.0, "%")
    assert "value" in u("Was HbA1c above 7 %?").requested
    c = u("Was the potassium below 5 mmol/L?").value_constraints[0]
    assert (c.comparator, c.value, c.unit) == ("<", 5.0, "mmol/L")
    c = u("Was blood pressure 150/95?").value_constraints[0]
    assert (c.comparator, c.value, c.value2) == ("=", 150.0, 95.0)
    c = u("Was HbA1c 7.8 %?").value_constraints[0]
    assert (c.comparator, c.value, c.unit) == ("=", 7.8, "%")


def test_dates_are_not_read_as_values():
    assert u("HbA1c on 12-Aug-2026").value_constraints == []
    assert u("What was HbA1c in May 2026?").value_constraints == []
    assert u("HbA1c on page 3").value_constraints == []


def test_advice_and_scope_flags():
    for text in ("Should I stop metformin?", "What treatment is recommended for diabetes?", "Can you diagnose me?",
                 "Will the patient recover?"):
        a = u(text)
        assert a.advice_request and any("never gives medical advice" in n for n in a.notes)
    assert not u("What medications is the patient taking?").advice_request


def test_assertion_focus_yes_no_and_notes():
    assert u("Is there a family history of diabetes?").assertion_focus == "family_history"
    assert u("Is the patient allergic to penicillin?").assertion_focus == "allergy"
    assert u("Was metformin discontinued?").assertion_focus == "discontinued"
    assert u("Does the patient have chest pain?").yes_no and not u("What is the HbA1c?").yes_no
    assert any("No clinical entity" in n for n in u("blood thinner").notes)
    assert any("two named entities" in n for n in u("Why is metformin used?").notes)


def test_never_invents_entities():
    a = u("Tell me about the weather")
    assert a.entities == [] and a.entity_types == {}
