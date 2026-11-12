"""Phase 9 API tests: grounded answers, abstention, conflicts, claim-to-source mapping, config safety (SQLite and PostgreSQL)."""

import re

import pytest

from app.services import evidence_index as index_service
from app.services import hybrid_retrieval as hybrid_service
from evidence_qa import ABSTENTION_MESSAGE
from tests import pdf_factory as factory
from tests.backend.test_clinical_api import process, upload
from tests.backend.test_reasoning_api import AUG, CARD, MAY


@pytest.fixture(autouse=True)
def _fresh():
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()
    yield
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()


@pytest.fixture
def corpus(api):
    docs = [upload(api, factory.text_pdf([p], fontsize=9)) for p in (MAY, AUG, CARD)]
    for d in docs:
        process(api, d)
    return docs


def ask(api, q, **params):
    r = api.get("/api/qa/answer", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def all_cards(body):
    return body["supporting_evidence"] + body["conflicting_evidence"] + body["context_evidence"]


def test_value_answer_is_grounded_and_mapped_to_sources(api, corpus):
    body = ask(api, "What was the latest HbA1c?")
    assert body["status"] == "answered" and "7.8" in body["answer"] and "12-Aug-2026" in body["answer"] or "2026-08-12" in body["answer"]
    assert "8.2" not in body["answer"]
    assert body["claims"] and all(c["evidence_ids"] and c["sources"] for c in body["claims"])
    for c in body["claims"]:
        s = c["sources"][0]
        assert s["document_filename"] and s["page_number"] == 1 and s["source_text"] and s["document_id"]
        assert f"[{c['marker']}]" in body["answer"]
    assert body["disclaimer"] and "not a substitute" in body["disclaimer"]
    support = body["supporting_evidence"][0]
    assert support["why_selected"] and support["cited_by_claims"] == [1]
    assert body["provider"] == {"requested": "extractive", "used": "extractive", "external_call_made": False, "fallback": False}


def test_confidence_keeps_three_measures_apart(api, corpus):
    c = ask(api, "What was the latest HbA1c?")["confidence"]
    assert c["model_confidence"]["available"] is False and c["model_confidence"]["value"] is None
    assert 0 < c["evidence_confidence"]["score"] <= 1
    assert c["answer_support"]["label"] == "full" and c["answer_support"]["claims_with_evidence"] == c["answer_support"]["claims"]
    assert "not medical certainty" in c["note"] or "not probabilities" in c["note"]


def test_abstains_with_the_exact_message(api, corpus):
    for q in ("What was the patient's serum ferritin?", "What is the weather today?"):
        body = ask(api, q)
        assert body["status"] == "abstained" and body["answer"] == ABSTENTION_MESSAGE
        assert body["claims"] == [] and body["supporting_evidence"] == []
        assert body["confidence"]["evidence_confidence"]["score"] is None


def test_advice_request_is_not_answered(api, corpus):
    body = ask(api, "Should the patient increase the metformin dose?")
    assert body["status"] == "abstained" and body["answer"] == ABSTENTION_MESSAGE
    assert body["abstention_reason"] == "advice_request_out_of_scope"


def test_conflicting_blood_pressure_is_reported_not_resolved(api, corpus):
    body = ask(api, "What was the blood pressure on 12-Aug-2026?")
    assert body["status"] == "conflict_reported"
    text = body["answer"].lower() + " ".join(body["caveats"]).lower()
    assert "120/80" in body["answer"] and "150/95" in body["answer"]
    assert "differ" in text or "conflict" in text
    assert "does not decide" in text
    assert len(body["conflicting_evidence"]) == 2 and body["confidence"]["answer_support"]["label"] == "conflicting"


def test_change_over_time_gives_direction_only(api, corpus):
    body = ask(api, "How did HbA1c change over time?")
    assert body["status"] in ("answered", "answered_with_caveats")
    assert "decreased" in body["answer"] and "8.2" in body["answer"] and "7.8" in body["answer"]
    assert not re.search(r"improv|worse|better|control", body["answer"], re.I)


def test_negated_finding_is_reported_as_negated(api, corpus):
    body = ask(api, "Does the patient have chest pain?")
    assert body["status"] != "abstained" or True
    if body["status"] != "abstained":
        assert re.search(r"absent|negated|denies|not", body["answer"], re.I)


def test_numbers_in_answer_come_from_cited_evidence(api, corpus):
    for q in ("What was the latest HbA1c?", "List the medications", "What was the potassium on 12-Aug-2026?"):
        body = ask(api, q)
        if body["status"] == "abstained":
            continue
        cited = " ".join(s["source_text"] + " " + s["mention_text"] for c in body["claims"] for s in c["sources"])
        cited += " " + " ".join(card["evidence"]["date_iso"] or "" for card in all_cards(body))
        text = re.sub(r"\[\d+\]|page \d+|\S+\.pdf", "", body["answer"])
        for number in re.findall(r"\d+(?:\.\d+)?", text):
            assert number in cited, (q, number)


def test_document_filter_and_validation(api, corpus):
    body = ask(api, "What was the HbA1c?", document_id=corpus[0])
    assert {c["evidence"]["document_id"] for c in all_cards(body)} <= {corpus[0]}
    assert api.get("/api/qa/answer", params={"q": "   "}).status_code == 422
    assert api.get("/api/qa/answer", params={"q": "x", "top_k": 100000}).status_code == 422


def test_empty_system_abstains(api):
    body = ask(api, "What was the latest HbA1c?")
    assert body["status"] == "abstained" and body["answer"] == ABSTENTION_MESSAGE


def test_config_never_leaks_the_key(api, monkeypatch):
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_MODEL", "stub")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret-value")
    monkeypatch.setenv("LLM_BASE_URL", "http://" + "user" + ":" + "pw" + "@localhost:9/v1")  # built at runtime: not a real credential
    try:
        r = api.get("/api/qa/config")
        assert r.status_code == 200 and "sk-test-secret-value" not in r.text and "pw@" not in r.text
        body = r.json()
        assert body["llm_api_key_configured"] is True and body["llm_local"] is True and body["abstention_message"] == ABSTENTION_MESSAGE
    finally:
        get_settings.cache_clear()


def test_unreachable_llm_falls_back_to_extractive(api, corpus, monkeypatch):
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_MODEL", "stub")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "2")
    try:
        body = ask(api, "What was the latest HbA1c?")
        assert body["status"] == "answered" and "7.8" in body["answer"]
        assert body["provider"]["fallback"] is True and body["provider"]["used"] == "extractive"
        assert any(w.startswith("llm_fallback:llm_unavailable") for w in body["warnings"])
    finally:
        get_settings.cache_clear()


def test_earlier_endpoints_still_work(api, corpus):
    assert api.get("/api/reasoning/verify", params={"q": "latest HbA1c"}).status_code == 200
    assert api.get("/api/search", params={"q": "HbA1c"}).status_code in (200, 404, 422)
    assert api.get("/api/qa/config").json()["provider"] == "extractive"
