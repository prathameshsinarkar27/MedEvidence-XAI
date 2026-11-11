"""Phase 8 API tests: question understanding + verification + conflict analysis over evidence extracted from synthetic PDFs
(SQLite and PostgreSQL)."""

import pytest

from app.services import evidence_index as index_service
from app.services import hybrid_retrieval as hybrid_service
from tests import pdf_factory as factory
from tests.backend.test_clinical_api import process, upload

MAY = ["SYNTHETIC NOTE MAY", "HbA1c was 8.2 % on 03-May-2026.", "Potassium 4.4 mmol/L on 03-May-2026.",
       "Metformin 500 mg twice daily.", "Patient reports chest pain."]
AUG = ["SYNTHETIC NOTE AUGUST", "HbA1c was 7.8 % on 12-Aug-2026.", "Potassium 4.1 mmol/L on 12-Aug-2026.",
       "Patient denies chest pain.", "Blood pressure 120/80 mmHg on 12-Aug-2026."]
CARD = ["SYNTHETIC CARDIOLOGY", "Blood pressure 150/95 mmHg on 12-Aug-2026.", "Metformin 500 mg for diabetes."]


@pytest.fixture(autouse=True)
def _fresh():
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()
    yield
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()


@pytest.fixture
def three_docs(api):
    return [upload(api, factory.text_pdf([p], fontsize=9)) for p in (MAY, AUG, CARD)]


@pytest.fixture
def corpus(api, three_docs):
    for d in three_docs:
        process(api, d)
    return three_docs


def verify(api, q, **params):
    r = api.get("/api/reasoning/verify", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def roles(body):
    return {(h["evidence"]["entity_name"], h["evidence"]["value_text"], h["evidence"]["date_iso"]): h["verification"]["role"]
            for h in body["ranked_evidence"]}


def test_response_follows_the_pipeline_and_contains_no_answer(api, corpus):
    body = verify(api, "What was the latest HbA1c?")
    assert set(body) == {"question", "understanding", "retrieval", "ranked_evidence", "conflict_analysis", "evidence_state", "note"}
    assert "Not yet evaluated" in body["note"] and "not an answer" in body["note"]
    assert body["understanding"]["primary"] == "value_lookup" and body["understanding"]["recency"] == "latest"
    assert body["retrieval"]["mode"] == "hybrid" and body["retrieval"]["formula"].startswith("final_score")
    assert not any(k in body for k in ("answer", "answers", "generated_answer"))
    hit = body["ranked_evidence"][0]
    assert hit["evidence"]["entity_name"] == "Hemoglobin A1c" and hit["evidence"]["value_text"] == "7.8"
    assert hit["evidence"]["document_filename"] and hit["evidence"]["page_number"] == 1 and hit["evidence"]["source_text"]
    assert hit["retrieval_rank"] == 1 and set(hit["retrieval_components"]) >= {"semantic", "entity", "temporal"}
    v = hit["verification"]
    assert v["role"] == "supporting" and v["directness"] == "direct" and v["constraints"]["recency"] == "met"
    applicable = [t for t in v["terms"].values() if t["score"] is not None]
    assert sum(t["contribution"] for t in applicable) == pytest.approx(v["score"], abs=1e-3)
    assert set(v["terms"]) == {"relevance", "entity", "value", "temporal", "confidence", "source", "directness", "agreement"}


def test_supported_with_temporal_change_listed_as_such(api, corpus):
    body = verify(api, "What was the latest HbA1c?")
    state = body["evidence_state"]
    assert state["state"] == "supported" and state["coverage"] == {"Hemoglobin A1c": "covered"}
    assert len(state["supporting_evidence_ids"]) == 1 and state["conflicting_evidence_ids"] == []
    ca = body["conflict_analysis"]
    assert ca["counts"] == {"temporal_change": 1, "measurement_variation": 0, "possible_contradiction": 0}
    pair = ca["pairs"][0]
    assert pair["category"] == "temporal_change" and pair["details"]["direction"] == "decreased" and len(pair["evidence_ids"]) == 2
    assert [p["value"] for p in ca["timelines"]["Hemoglobin A1c"]] == ["8.2", "7.8"]


def test_comparison_across_two_months(api, corpus):
    body = verify(api, "Compare HbA1c in May 2026 and August 2026")
    assert body["understanding"]["primary"] == "comparison" and len(body["understanding"]["periods"]) == 2
    assert body["evidence_state"]["state"] == "supported"
    assert any(r["code"] == "comparison_points" for r in body["evidence_state"]["reasons"])


def test_period_without_evidence_is_partial(api, corpus):
    body = verify(api, "What was the HbA1c in June 2026?")
    assert body["evidence_state"]["state"] == "partially_supported"
    assert body["evidence_state"]["supporting_evidence_ids"] == []
    assert any(r["code"] == "found_outside_constraints" for r in body["evidence_state"]["reasons"])


def test_same_day_blood_pressure_in_two_documents_is_conflicting(api, corpus):
    body = verify(api, "What is the blood pressure on 12-Aug-2026?")
    state = body["evidence_state"]
    assert state["state"] == "conflicting" and len(state["conflicting_evidence_ids"]) == 2
    pair = [p for p in body["conflict_analysis"]["pairs"] if p["category"] == "possible_contradiction"][0]
    assert pair["strength"] == "moderate" and pair["in_scope"] and pair["details"]["date_a"] == "2026-08-12"
    docs = {h["evidence"]["document_id"] for h in body["ranked_evidence"] if h["evidence"]["entity_name"] == "Blood pressure"}
    assert len(docs) == 2  # the two values come from two different documents


def test_opposite_statements_without_dates_conflict_weakly(api, corpus):
    body = verify(api, "Does the patient have chest pain?")
    assert body["evidence_state"]["state"] == "conflicting"
    pair = body["conflict_analysis"]["pairs"][0]
    assert pair["reason"] == "opposite_assertions_time_unknown" and pair["strength"] == "weak"
    assert {h["evidence"]["assertion"] for h in body["ranked_evidence"] if h["evidence"]["entity_name"] == "Chest pain"} == {"affirmed", "negated"}


def test_relationship_supported_by_same_sentence_co_mention(api, corpus):
    body = verify(api, "Is metformin prescribed for diabetes?")
    assert body["evidence_state"]["state"] == "supported"
    assert any(r["code"] == "co_mentioned_same_sentence" and "not interpreted" in r["text"] for r in body["evidence_state"]["reasons"])


def test_list_question_retrieves_only_the_requested_type(api, corpus):
    body = verify(api, "List all medications")
    assert body["evidence_state"]["state"] == "supported" and body["retrieval"]["filters"] == {"entity_type": "medication"}
    assert {h["evidence"]["entity_type"] for h in body["ranked_evidence"]} == {"medication"}


def test_missing_entity_and_advice_requests_are_insufficient(api, corpus):
    assert verify(api, "What is the sodium level?")["evidence_state"]["state"] == "insufficient_evidence"
    advice = verify(api, "Should I stop metformin?")
    assert advice["evidence_state"]["state"] == "insufficient_evidence" and advice["understanding"]["advice_request"]
    assert advice["evidence_state"]["reasons"][0]["code"] == "advice_request_out_of_scope"


def test_claim_assessment_for_a_stated_value(api, corpus):
    body = verify(api, "Was HbA1c above 8 %?")
    assert body["understanding"]["value_constraints"][0]["comparator"] == ">"
    assert body["evidence_state"]["claim_assessment"] == "mixed"
    checks = {h["evidence"]["value_text"]: h["verification"]["claim_check"] for h in body["ranked_evidence"]
              if h["evidence"]["entity_name"] == "Hemoglobin A1c"}
    assert checks == {"8.2": "confirms", "7.8": "contradicts"}


def test_document_filter_limits_retrieval(api, corpus):
    may_id = corpus[0]
    body = verify(api, "What is the HbA1c?", document_id=may_id)
    assert {h["evidence"]["document_id"] for h in body["ranked_evidence"]} == {may_id}
    assert body["retrieval"]["filters"]["document_id"] == may_id
    assert body["conflict_analysis"]["counts"]["temporal_change"] == 0


def test_verification_does_not_change_stored_evidence(api, corpus):
    before = api.get("/api/evidence", params={"limit": 1000}).json()
    verify(api, "What is the HbA1c?")
    verify(api, "Compare HbA1c over time")
    assert api.get("/api/evidence", params={"limit": 1000}).json() == before


def test_understand_endpoint_and_config(api):
    body = api.get("/api/reasoning/understand", params={"q": "Was HbA1c above 7 % in May 2026?"}).json()
    assert body["entities"] == ["Hemoglobin A1c"] and body["periods"] == [["2026-05-01", "2026-05-31"]]
    assert body["value_constraints"][0]["value"] == 7.0 and "temporal" in body["types"]
    cfg = api.get("/api/reasoning/config").json()
    assert set(cfg["weights"]) == set(cfg["component_descriptions"]) and len(cfg["weights"]) == 8
    assert cfg["evidence_states"] == ["supported", "partially_supported", "conflicting", "insufficient_evidence"]
    assert cfg["conflict_categories"] == ["temporal_change", "measurement_variation", "possible_contradiction"]
    assert cfg["thresholds"]["supported_score"] == 0.7 and "Not yet evaluated" in cfg["note"]


def test_settings_change_the_result(api, corpus, configure):
    assert verify(api, "What is the HbA1c on 12-Aug-2026?")["evidence_state"]["state"] == "supported"
    configure(VERIFY_SUPPORTED_SCORE="0.999")
    body = verify(api, "What is the HbA1c on 12-Aug-2026?")
    assert body["evidence_state"]["state"] == "partially_supported" and api.get("/api/reasoning/config").json()["thresholds"]["supported_score"] == 0.999
    configure(VERIFY_SUPPORTED_SCORE="0.7", CONFLICT_TOLERANCE_VITAL="0.5")
    bp = verify(api, "What is the blood pressure on 12-Aug-2026?")
    assert bp["evidence_state"]["state"] == "supported" and bp["conflict_analysis"]["counts"]["measurement_variation"] == 1


def test_validation_and_limits(api):
    assert api.get("/api/reasoning/verify", params={"q": ""}).status_code == 422
    assert api.get("/api/reasoning/verify", params={"q": "   "}).json()["detail"]["code"] == "empty_question"
    assert api.get("/api/reasoning/verify", params={"q": "x" * 501}).status_code == 422
    assert api.get("/api/reasoning/verify", params={"q": "x", "top_k": 1000}).json()["detail"]["code"] == "top_k_too_large"
    assert api.get("/api/reasoning/verify", params={"q": "x", "document_id": "not-a-uuid"}).status_code == 422
    assert api.get("/api/reasoning/understand", params={"q": "  "}).json()["detail"]["code"] == "empty_question"


def test_empty_database_is_insufficient_not_an_error(api):
    body = verify(api, "What is the HbA1c?")
    assert body["evidence_state"]["state"] == "insufficient_evidence" and body["ranked_evidence"] == [] and body["retrieval"]["warnings"]


def test_works_without_vectors_and_says_so(api, configure):
    configure(AUTO_INDEX_EVIDENCE="false")
    d = upload(api, factory.text_pdf([AUG], fontsize=9))
    process(api, d)
    body = verify(api, "What is the HbA1c?")
    assert body["retrieval"]["semantic_available"] is False and body["retrieval"]["warnings"]
    hit = body["ranked_evidence"][0]
    assert hit["verification"]["terms"]["relevance"]["score"] is None and hit["verification"]["role"] == "supporting"
    assert body["evidence_state"]["state"] == "supported"


def test_deterministic(api, corpus):
    a = verify(api, "What is the HbA1c?")
    b = verify(api, "What is the HbA1c?")
    assert [h["evidence"]["evidence_id"] for h in a["ranked_evidence"]] == [h["evidence"]["evidence_id"] for h in b["ranked_evidence"]]
    assert a["evidence_state"] == b["evidence_state"]


def test_earlier_phase_endpoints_still_work(api, corpus):
    assert api.get("/api/evidence/hybrid-search", params={"q": "HbA1c"}).status_code == 200
    assert api.get("/api/evidence/search", params={"q": "HbA1c"}).status_code == 200
    assert api.get("/api/evidence/ranking-config").status_code == 200
    assert api.get("/api/health").status_code == 200
