"""Phase 7 API tests: hybrid retrieval + ranking over evidence extracted from synthetic PDFs (SQLite and PostgreSQL)."""

import uuid

import pytest

from app.services import evidence_index as index_service
from app.services import hybrid_retrieval as hybrid_service
from tests import pdf_factory as factory
from tests.backend.test_clinical_api import narrative_pdf, process, upload

MAY = ["SYNTHETIC NOTE MAY", "HbA1c was 8.2 % on 03-May-2026.", "Potassium 4.4 mmol/L on 03-May-2026.",
       "Metformin 500 mg twice daily."]
AUG = ["SYNTHETIC NOTE AUGUST", "HbA1c was 7.8 % on 12-Aug-2026.", "Potassium 4.1 mmol/L on 12-Aug-2026.",
       "Patient denies chest pain."]


@pytest.fixture(autouse=True)
def _fresh():
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()
    yield
    index_service.clear_index_cache()
    hybrid_service.clear_corpus_cache()


@pytest.fixture
def two_docs(api):
    d1 = upload(api, factory.text_pdf([MAY], fontsize=9))
    d2 = upload(api, factory.text_pdf([AUG], fontsize=9))
    process(api, d1)
    process(api, d2)
    return d1, d2


def hs(api, q, **params):
    r = api.get("/api/evidence/hybrid-search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_hybrid_response_shape_and_breakdown_sums(api, two_docs):
    body = hs(api, "HbA1c", top_k=3)
    assert body["mode"] == "hybrid" and body["formula"].startswith("final_score = w_semantic * semantic")
    assert set(body["weights"]) == {"semantic", "keyword", "entity", "temporal", "confidence", "source"}
    assert body["analysis"]["entities"] == ["Hemoglobin A1c"] and "Not yet evaluated" in body["note"]
    assert body["returned"] == len(body["hits"]) <= 3
    for hit in body["hits"]:
        assert hit["final_score"] == pytest.approx(sum(c["contribution"] for c in hit["components"].values()), abs=1e-4)
        for c in hit["components"].values():
            assert 0 <= c["score"] <= 1 and c["contribution"] == pytest.approx(c["score"] * c["weight"], abs=1e-5)
        assert hit["evidence"]["document_filename"] == "report.pdf" or hit["evidence"]["document_filename"]
    scores = [h["final_score"] for h in body["hits"]]
    assert scores == sorted(scores, reverse=True) and [h["rank"] for h in body["hits"]] == list(range(1, len(scores) + 1))
    assert body["hits"][0]["evidence"]["entity_name"] == "Hemoglobin A1c"


def test_default_weights_come_from_configuration(api, two_docs, configure):
    configure(RANK_WEIGHT_ENTITY="3.5", RANK_WEIGHT_SEMANTIC="0")
    cfg = api.get("/api/evidence/ranking-config").json()
    assert cfg["weights"]["entity"] == 3.5 and cfg["weights"]["semantic"] == 0 and len(cfg["components"]) == 6
    assert hs(api, "HbA1c")["weights"]["entity"] == 3.5
    assert set(cfg["descriptions"]) == set(cfg["components"])


def test_weight_overrides_and_validation(api, two_docs):
    assert hs(api, "HbA1c", w_entity=0, w_keyword=7)["weights"]["keyword"] == 7
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "w_entity": -1}).status_code == 422
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "w_entity": 101}).status_code == 422


def test_modes_use_single_component(api, two_docs):
    for mode in ("semantic", "keyword", "entity"):
        body = hs(api, "potassium", mode=mode)
        assert body["weights"][mode] == 1.0 and sum(body["weights"].values()) == 1.0
        assert all(h["components"][mode]["score"] > 0 for h in body["hits"])
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "mode": "bogus"}).status_code == 422


def test_exact_date_query_ranks_matching_date_first(api, two_docs):
    top = hs(api, "HbA1c on 12-Aug-2026", top_k=3)["hits"]
    assert top[0]["evidence"]["entity_name"] == "Hemoglobin A1c" and top[0]["evidence"]["date_iso"] == "2026-08-12"
    assert top[0]["components"]["temporal"]["score"] == 1.0 and "within the requested period" in top[0]["temporal_note"]


def test_month_year_and_recency_queries(api, two_docs):
    may = hs(api, "potassium in May 2026", top_k=2)["hits"][0]["evidence"]
    assert may["entity_name"] == "Potassium" and may["date_iso"] == "2026-05-03"
    latest = hs(api, "latest potassium", top_k=2)
    assert latest["analysis"]["recency"] == "latest" and latest["hits"][0]["evidence"]["date_iso"] == "2026-08-12"
    earliest = hs(api, "earliest HbA1c", top_k=1)["hits"][0]["evidence"]
    assert earliest["date_iso"] == "2026-05-03" and earliest["value_text"] == "8.2"


def test_synonym_resolution_via_lexicon(api, two_docs):
    body = hs(api, "A1c", top_k=2)
    assert body["analysis"]["entities"] == ["Hemoglobin A1c"]
    assert {h["evidence"]["entity_name"] for h in body["hits"]} == {"Hemoglobin A1c"}


def test_filters_apply_and_date_range(api, two_docs):
    d1, d2 = two_docs
    only = hs(api, "potassium", document_id=d2, top_k=20)
    assert only["hits"] and all(h["evidence"]["document_id"] == d2 for h in only["hits"]) and only["filters"]["document_id"] == d2
    ranged = hs(api, "potassium", date_from="2026-06-01", top_k=20)["hits"]
    assert ranged and all(h["evidence"]["date_iso"] >= "2026-06-01" for h in ranged)
    assert hs(api, "potassium", date_to="2026-01-01")["hits"] == []
    assert hs(api, "chest pain", assertion="negated")["hits"][0]["evidence"]["assertion"] == "negated"
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "date_from": "2026-13-45"}).json()["detail"]["code"] == "invalid_date"
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "date_from": "yesterday"}).status_code == 422


def test_no_match_returns_empty_and_limits_enforced(api, two_docs):
    assert isinstance(hs(api, "zzzqqq")["hits"], list)
    assert api.get("/api/evidence/hybrid-search", params={"q": "x", "top_k": 1000}).json()["detail"]["code"] == "top_k_too_large"
    assert api.get("/api/evidence/hybrid-search", params={"q": "   "}).json()["detail"]["code"] == "empty_query"
    assert api.get("/api/evidence/hybrid-search", params={"q": ""}).status_code == 422


def test_empty_database_is_not_an_error(api):
    body = hs(api, "HbA1c")
    assert body["hits"] == [] and body["semantic_available"] is False and body["warnings"]


def test_unindexed_documents_still_found_by_keyword_entity_with_warning(api, configure):
    configure(AUTO_INDEX_EVIDENCE="false")
    d = upload(api, factory.text_pdf([MAY], fontsize=9))
    process(api, d)
    body = hs(api, "HbA1c")
    assert body["hits"] and body["semantic_available"] is False and any("vector" in w.lower() for w in body["warnings"])
    assert body["hits"][0]["components"]["semantic"]["score"] == 0


def test_semantic_unavailable_degrades_in_hybrid_but_fails_in_semantic_mode(api, two_docs, configure):
    configure(EMBEDDING_BACKEND="sentence-transformers", EMBEDDING_MODEL="no/such-model", EMBEDDING_LOCAL_FILES_ONLY="true")
    body = hs(api, "HbA1c")
    assert body["hits"] and any("unavailable" in w for w in body["warnings"]) and body["semantic_available"] is False
    r = api.get("/api/evidence/hybrid-search", params={"q": "HbA1c", "mode": "semantic"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "embedding_unavailable"
    assert hs(api, "HbA1c", w_semantic=0)["warnings"] == []  # not asked for -> not attempted


def test_new_documents_visible_without_restart_and_reprocessing_updates(api, two_docs):
    assert hs(api, "lisinopril")["hits"] == [] or hs(api, "lisinopril")["hits"][0]["evidence"]["entity_name"] != "Lisinopril"
    d3 = upload(api, factory.text_pdf([["Lisinopril 10 mg once daily."]], fontsize=9))
    process(api, d3)
    assert hs(api, "lisinopril")["hits"][0]["evidence"]["entity_name"] == "Lisinopril"
    assert api.post(f"/api/documents/{d3}/process").status_code == 202
    assert hs(api, "lisinopril")["hits"][0]["evidence"]["document_id"] == d3


def test_ranking_is_deterministic(api, two_docs):
    a = [h["evidence"]["evidence_id"] for h in hs(api, "potassium results", top_k=10)["hits"]]
    b = [h["evidence"]["evidence_id"] for h in hs(api, "potassium results", top_k=10)["hits"]]
    assert a == b


def test_phase6_search_unchanged(api, two_docs):
    body = api.get("/api/evidence/search", params={"q": "potassium"}).json()
    assert body["hits"] and "score" in body["hits"][0] and "components" not in body["hits"][0]


def test_hybrid_hit_evidence_equals_phase5_record(api, two_docs):
    hit = hs(api, "HbA1c", top_k=1)["hits"][0]["evidence"]
    one = api.get(f"/api/evidence/{hit['evidence_id']}").json()
    assert hit == one
    assert api.get(f"/api/evidence/{uuid.uuid4()}").status_code == 404
