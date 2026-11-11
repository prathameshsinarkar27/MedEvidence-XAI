"""Per-evidence verification: transparent score, directness, constraints, roles, claim checks."""

import pytest

from evidence_reasoning import ReasoningConfig, VerifyWeights, analyze_conflicts, understand_question as u
from evidence_reasoning.verification import claim_check, recency_targets, verify_item
from tests.evidence_reasoning.helpers import ev, finding


def run(question, e, others=(), cfg=None):
    q = u(question)
    cfg = cfg or ReasoningConfig()
    allev = [e, *others]
    return verify_item(e, q, recency_targets(allev, q), analyze_conflicts(allev, cfg), cfg)


def test_score_is_the_weighted_mean_of_applicable_components():
    v = run("What is the HbA1c?", ev())
    applicable = {k: t for k, t in v.terms.items() if t["score"] is not None}
    assert "temporal" not in applicable  # no time constraint in the question
    total_w = sum(t["weight"] for t in applicable.values())
    assert v.score == pytest.approx(sum(t["weight"] * t["score"] for t in applicable.values()) / total_w, abs=1e-3)
    assert sum(t["contribution"] for t in applicable.values()) == pytest.approx(v.score, abs=1e-3)
    assert v.terms["temporal"]["score"] is None and v.terms["temporal"]["contribution"] is None
    assert 0 <= v.score <= 1


def test_weights_are_configuration():
    cfg = ReasoningConfig(weights=VerifyWeights(relevance=0, entity=0, value=0, temporal=0, confidence=1, source=0, directness=0, agreement=0))
    assert run("What is the HbA1c?", ev(conf=0.42), cfg=cfg).score == pytest.approx(0.42, abs=1e-3)
    with pytest.raises(ValueError):
        VerifyWeights(entity=-1)


def test_relevance_is_not_applicable_without_vectors():
    v = run("What is the HbA1c?", ev(sem=None))
    assert v.terms["relevance"]["score"] is None and "unavailable" in v.terms["relevance"]["note"]


def test_directness_levels():
    assert run("What is the HbA1c?", ev()).directness == "direct"
    assert run("What is the HbA1c?", ev("Potassium", "4.1", unit="mmol/L")).directness == "not_relevant"
    partial = run("What is the glucose?", ev("Fasting glucose", "95", unit="mg/dL"))
    assert partial.directness == "indirect" and "entity_only_partially_matches" in partial.directness_reasons
    no_value = run("What is the HbA1c value?", ev(value=None, numeric=None))
    assert no_value.directness == "indirect" and "no_value_stated" in no_value.directness_reasons
    unnamed = run("blood thinner", ev())
    assert unnamed.directness == "indirect" and "entity_not_identified" in unnamed.directness_reasons


def test_assertion_decides_whether_evidence_addresses_the_question():
    assert run("Does the patient have diabetes?", finding("Diabetes mellitus", assertion="negated")).directness == "direct"
    fam = run("Does the patient have diabetes?", finding("Diabetes mellitus", assertion="family_history"))
    assert fam.directness == "indirect" and fam.assertion_note and "family history" in fam.assertion_note
    assert run("Is there a family history of diabetes?", finding("Diabetes mellitus", assertion="family_history")).directness == "direct"
    stopped = run("Is the patient taking metformin?", finding("Metformin", "medication", "discontinued"))
    assert stopped.directness == "indirect"


def test_period_constraint():
    inside, outside, undated = ev(date="2026-08-12"), ev(date="2026-05-03"), ev(date=None)
    q = "HbA1c in August 2026"
    assert (run(q, inside).constraints["period"], run(q, outside).constraints["period"], run(q, undated).constraints["period"]) == ("met", "unmet", "unknown")
    assert run(q, inside).in_scope and not run(q, outside).in_scope and not run(q, undated).in_scope
    assert run(q, inside).terms["temporal"]["score"] == 1.0 and run(q, outside).terms["temporal"]["score"] == 0.0
    assert run(q, undated).terms["temporal"]["score"] == ReasoningConfig().undated_temporal_score
    assert "outside_period" in run(q, outside).directness_reasons and "date_unknown" in run(q, undated).directness_reasons


def test_recency_constraint_uses_the_latest_dated_value_of_that_entity():
    old, new = ev(value="8.2", date="2026-05-03"), ev(value="7.8", date="2026-08-12")
    assert run("latest HbA1c", new, [old]).constraints["recency"] == "met"
    assert run("latest HbA1c", old, [new]).constraints["recency"] == "unmet"
    assert run("earliest HbA1c", old, [new]).constraints["recency"] == "met"
    assert run("latest HbA1c", ev(date=None), [new]).constraints["recency"] == "unknown"
    assert run("latest HbA1c", ev(date=None)).constraints["recency"] == "unknown"  # no dated value at all: cannot establish


def test_recency_is_per_entity():
    k_old, k_new = ev("Potassium", "4.4", "2026-05-03", unit="mmol/L"), ev("Potassium", "4.1", "2026-08-12", unit="mmol/L")
    a1c = ev(date="2026-01-01")
    assert run("latest HbA1c and potassium", a1c, [k_old, k_new]).constraints["recency"] == "met"


def test_page_constraint():
    assert run("HbA1c on page 2", ev(page=2)).constraints["page"] == "met"
    other = run("HbA1c on page 2", ev(page=1))
    assert other.constraints["page"] == "unmet" and not other.in_scope and "other_page" in other.directness_reasons


def test_source_and_value_consistency_terms():
    assert run("What is the HbA1c?", ev(modality="ocr", ocr_confidence=60)).terms["source"]["score"] == 0.6
    assert run("What is the HbA1c?", ev(modality="ocr", ocr_confidence=None)).terms["source"]["score"] == 0.5
    assert run("What is the HbA1c?", ev(modality="table")).terms["source"]["score"] == 1.0
    assert run("What is the HbA1c?", ev(attributes={"implausible_value": True})).terms["value"]["score"] == 0.0
    assert run("What is the HbA1c?", ev(unit=None, etype="lab_result", value="7.8")).terms["value"]["score"] == 0.5
    assert run("What is the HbA1c?", finding("Hemoglobin A1c", "lab_result")).terms["value"]["score"] is None


def test_agreement_rises_with_corroboration_and_falls_with_contradiction():
    a = ev(value="7.8")
    twin = ev(value="7.8", doc="d2")
    clash = ev(value="9.5", doc="d3")
    alone = run("What is the HbA1c?", a)
    corroborated = run("What is the HbA1c?", a, [twin])
    contradicted = run("What is the HbA1c?", a, [clash])
    assert alone.terms["agreement"]["score"] == 1.0 and corroborated.corroborating_ids == [twin.id]
    assert contradicted.terms["agreement"]["score"] == 0.5 and contradicted.conflict_ids == [clash.id]
    assert contradicted.score < alone.score


@pytest.mark.parametrize("question,value,verdict", [
    ("Was HbA1c above 7 %?", "7.8", "confirms"), ("Was HbA1c above 8 %?", "7.8", "contradicts"),
    ("Was HbA1c 7.8 %?", "7.8", "confirms"), ("Was HbA1c below 7.8 %?", "7.8", "contradicts"),
    ("Was HbA1c at least 7.8 %?", "7.8", "confirms"),
])
def test_claim_check(question, value, verdict):
    assert claim_check(ev(value=value), u(question)) == verdict


def test_claim_check_undetermined_and_blood_pressure():
    assert claim_check(ev(unit="mmol/mol", value="62"), u("Was HbA1c above 7 %?")) == "undetermined"  # unit differs: no conversion
    assert claim_check(ev(), u("What is the HbA1c?")) is None
    from tests.evidence_reasoning.helpers import bp
    assert claim_check(bp(150, 95), u("Was blood pressure 150/95?")) == "confirms"
    assert claim_check(bp(120, 80), u("Was blood pressure 150/95?")) == "contradicts"


def test_roles_follow_score_gates():
    assert run("What is the HbA1c?", ev()).role == "supporting"
    assert run("What is the HbA1c?", ev("Potassium", "4.1", unit="mmol/L")).role == "excluded"
    strict = ReasoningConfig(supported_score=0.99)
    assert run("What is the HbA1c?", ev(), cfg=strict).role == "context"
    loose = ReasoningConfig(min_relevant_score=0.99)
    assert run("What is the HbA1c?", ev(), cfg=loose).role == "excluded"


def test_without_an_entity_only_strong_semantic_similarity_makes_evidence_relevant():
    assert run("blood thinner", ev(sem=0.1)).role == "excluded"
    assert run("blood thinner", ev(sem=0.6)).role == "context"  # never supporting: entity cannot be checked
    assert run("blood thinner", ev(sem=None)).role == "excluded"
