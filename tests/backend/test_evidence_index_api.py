"""Phase 6 API tests: evidence index, semantic search, structured retrieval. Synthetic PDFs only.

Run on SQLite and (if TEST_DATABASE_URL is set) PostgreSQL.
"""

import uuid

import pytest
from sqlalchemy import func, select, update

from app.models.document import Document
from app.models.evidence_embedding import EvidenceEmbedding
from app.services import evidence_index as index_service
from tests import pdf_factory as factory
from tests.backend.test_clinical_api import NARRATIVE, evidence, narrative_pdf, process, set_columns, upload

SECOND = ["SYNTHETIC SECOND REPORT", "Patient reports cough and headache.", "Lisinopril 10 mg once daily.",
          "Potassium 4.1 mmol/L on 03-Sep-2026."]


@pytest.fixture(autouse=True)
def _fresh_cache():
    index_service.clear_index_cache()
    yield
    index_service.clear_index_cache()


def idx_status(api, doc_id):
    return api.get(f"/api/documents/{doc_id}/evidence-index").json()


def embedding_count(api, doc_id=None):
    with api.session_factory() as s:
        q = select(func.count()).select_from(EvidenceEmbedding)
        if doc_id:
            q = q.where(EvidenceEmbedding.document_id == uuid.UUID(doc_id))
        return s.scalar(q)


def search(api, q, **params):
    r = api.get("/api/evidence/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def doc(api):
    d = upload(api, narrative_pdf())
    process(api, d)
    return d


def test_automatic_indexing_after_clinical_extraction(api, doc):
    n = len(evidence(api, doc))
    st = idx_status(api, doc)
    assert n > 0 and st["index_status"] == "completed" and st["indexed_count"] == n and not st["stale"]
    assert st["index_model"] == st["current_model"] == "hashing-v1-d512" and "Not yet evaluated" in st["note"]
    assert embedding_count(api, doc) == n


def test_not_indexed_before_anything_and_manual_start_requires_clinical(api):
    d = upload(api, narrative_pdf())
    assert idx_status(api, d)["index_status"] == "not_processed"
    r = api.post(f"/api/documents/{d}/evidence-index")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "clinical_not_processed"
    assert api.get(f"/api/documents/{uuid.uuid4()}/evidence-index").status_code == 404
    assert api.post(f"/api/documents/{uuid.uuid4()}/evidence-index").status_code == 404


def test_auto_index_can_be_switched_off_then_run_manually(api, doc, configure):
    configure(AUTO_INDEX_EVIDENCE="false")
    d = upload(api, narrative_pdf())
    process(api, d)
    assert idx_status(api, d)["index_status"] == "not_processed"
    assert api.post(f"/api/documents/{d}/evidence-index").status_code == 202
    assert idx_status(api, d)["index_status"] == "completed"


def test_search_finds_chest_pain_with_full_provenance(api, doc):
    body = search(api, "chest pain", top_k=3)
    top = body["hits"][0]
    assert body["embedding_model"] == "hashing-v1-d512" and body["is_semantic"] is False
    assert "Not yet evaluated" in body["note"] and body["returned"] == len(body["hits"]) <= 3
    ev = top["evidence"]
    assert ev["entity_name"] == "Chest pain" and ev["assertion"] == "negated" and top["rank"] == 1
    assert ev["document_id"] == doc and ev["document_filename"] == "report.pdf" and ev["page_number"] == 1
    assert ev["source_text"] and ev["mention_text"] and "negated" in top["embedding_text"]
    scores = [h["score"] for h in body["hits"]]
    assert scores == sorted(scores, reverse=True)


def test_search_evidence_matches_phase5_row_exactly(api, doc):
    hit = search(api, "HbA1c", top_k=1)["hits"][0]["evidence"]
    original = next(i for i in evidence(api, doc) if i["evidence_id"] == hit["evidence_id"])
    assert {k: hit[k] for k in original} == original


@pytest.mark.parametrize("filters,check", [
    ({"entity_type": "medication"}, lambda e: e["entity_type"] == "medication"),
    ({"assertion": "negated"}, lambda e: e["assertion"] == "negated"),
    ({"modality": "text"}, lambda e: e["modality"] == "text"),
    ({"page_number": 1}, lambda e: e["page_number"] == 1),
    ({"min_confidence": 0.8}, lambda e: e["extraction_confidence"] >= 0.8),
    ({"entity_name": "metformin"}, lambda e: e["entity_name"].lower() == "metformin"),
])
def test_filters_apply_before_ranking(api, doc, filters, check):
    body = search(api, "pain", top_k=50, **filters)
    assert body["hits"] and all(check(h["evidence"]) for h in body["hits"])
    assert body["candidates"] == len(body["hits"]) or body["candidates"] >= len(body["hits"])
    assert body["filters"]


def test_filter_with_no_match_returns_empty(api, doc):
    body = search(api, "pain", page_number=99)
    assert body["hits"] == [] and body["candidates"] == 0


def test_multi_document_search_and_document_filter(api, doc):
    d2 = upload(api, factory.text_pdf([SECOND], fontsize=9))
    process(api, d2)
    hits = search(api, "lisinopril", top_k=5)["hits"]
    assert hits[0]["evidence"]["document_id"] == d2
    only1 = search(api, "lisinopril", top_k=50, document_id=doc)["hits"]
    assert only1 and all(h["evidence"]["document_id"] == doc for h in only1)
    assert api.get("/api/evidence/index").json()["indexed_documents"] == 2


def test_min_score_and_top_k_limits(api, doc):
    assert search(api, "chest pain", min_score=0.99)["hits"] == []
    assert len(search(api, "pain", top_k=1)["hits"]) == 1
    assert api.get("/api/evidence/search", params={"q": "x", "top_k": 0}).status_code == 422
    assert api.get("/api/evidence/search", params={"q": "x", "top_k": 1000}).json()["detail"]["code"] == "top_k_too_large"
    assert api.get("/api/evidence/search", params={"q": ""}).status_code == 422
    assert api.get("/api/evidence/search", params={"q": "   "}).json()["detail"]["code"] == "empty_query"
    assert api.get("/api/evidence/search", params={"q": "x" * 501}).status_code == 422
    assert api.get("/api/evidence/search", params={"q": "x", "entity_type": "bogus"}).status_code == 422


def test_search_empty_index_is_empty_not_error(api):
    body = search(api, "anything")
    assert body["hits"] == []


def test_browse_by_document_page_entity(api, doc):
    all_items = evidence(api, doc)
    r = api.get("/api/evidence", params={"document_id": doc, "limit": 1000}).json()
    assert r["total"] == len(all_items) and [i["evidence_id"] for i in r["items"]] == [i["evidence_id"] for i in all_items]
    assert all(i["document_filename"] == "report.pdf" for i in r["items"])
    p = api.get("/api/evidence", params={"document_id": doc, "page_number": 1}).json()
    assert p["total"] == len(all_items)
    assert api.get("/api/evidence", params={"document_id": doc, "page_number": 2}).json()["total"] == 0
    m = api.get("/api/evidence", params={"entity_name": "METFORMIN"}).json()
    assert m["total"] >= 1 and all(i["entity_name"] == "Metformin" for i in m["items"])
    page = api.get("/api/evidence", params={"limit": 2, "offset": 1}).json()
    assert len(page["items"]) == 2 and page["offset"] == 1


def test_entities_listing_and_single_evidence(api, doc):
    ents = api.get("/api/evidence/entities").json()
    names = {i["entity_name"] for i in ents["items"]}
    assert {"Chest pain", "Metformin"} <= names and ents["total"] == len(ents["items"])
    meds = api.get("/api/evidence/entities", params={"entity_type": "medication"}).json()["items"]
    assert meds and all(i["entity_type"] == "medication" for i in meds)
    first = api.get("/api/evidence", params={"limit": 1}).json()["items"][0]
    one = api.get(f"/api/evidence/{first['evidence_id']}")
    assert one.status_code == 200 and one.json()["evidence_id"] == first["evidence_id"]
    assert api.get(f"/api/evidence/{uuid.uuid4()}").status_code == 404
    assert api.get("/api/evidence/not-a-uuid").status_code == 422


def test_overview(api, doc):
    o = api.get("/api/evidence/index").json()
    assert o["embedding_backend"] == "hashing" and o["is_semantic"] is False and o["embedding_available"] is True
    assert o["indexed_evidence"] == o["evidence_total"] == len(evidence(api, doc)) and o["stale_documents"] == 0
    assert o["vector_backend"] == "faiss" and o["vector_backend_available"] and "Not yet evaluated" in o["note"]


def test_reprocessing_clinical_replaces_vectors(api, doc):
    before = embedding_count(api, doc)
    assert api.post(f"/api/documents/{doc}/clinical-extraction").status_code == 202
    assert idx_status(api, doc)["index_status"] == "completed" and embedding_count(api, doc) == before
    with api.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(EvidenceEmbedding)) == before


def test_reprocessing_text_drops_vectors_and_resets_status(api, doc, configure):
    configure(AUTO_CLINICAL_EXTRACTION="false")
    process(api, doc)
    assert embedding_count(api, doc) == 0 and idx_status(api, doc)["index_status"] == "not_processed"
    assert search(api, "chest pain")["hits"] == []


def test_search_reflects_new_documents_without_restart(api, doc):
    assert search(api, "lisinopril")["hits"][0]["evidence"]["entity_name"] != "Lisinopril"
    d2 = upload(api, factory.text_pdf([SECOND], fontsize=9))
    process(api, d2)
    assert search(api, "lisinopril")["hits"][0]["evidence"]["entity_name"] == "Lisinopril"


def test_vector_backends_give_same_ranking(api, doc, configure):
    a = [h["evidence"]["evidence_id"] for h in search(api, "diabetes medication", top_k=5)["hits"]]
    configure(VECTOR_BACKEND="numpy")
    index_service.clear_index_cache()
    body = search(api, "diabetes medication", top_k=5)
    assert body["vector_backend"] == "numpy"
    assert [h["evidence"]["evidence_id"] for h in body["hits"]] == a


def test_embedding_unavailable_is_clear_failure_not_silent(api, doc, configure):
    configure(EMBEDDING_BACKEND="sentence-transformers", EMBEDDING_MODEL="no/such-model", EMBEDDING_LOCAL_FILES_ONLY="true")
    r = api.get("/api/evidence/search", params={"q": "chest pain"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "embedding_unavailable" and r.json()["detail"]["message"]
    assert api.post(f"/api/documents/{doc}/evidence-index").status_code == 202
    st = idx_status(api, doc)
    assert st["index_status"] == "failed" and st["error_code"] == "embedding_unavailable" and st["error_message"]
    o = api.get("/api/evidence/index").json()
    assert o["embedding_available"] is False and o["embedding_message"] and o["is_semantic"] is True
    assert len(evidence(api, doc)) > 0  # clinical evidence itself is untouched


def test_changing_model_marks_documents_stale_and_rebuild_fixes(api, doc, configure):
    configure(EMBEDDING_DIMENSION="256")
    st = idx_status(api, doc)
    assert st["stale"] is True and st["current_model"] == "hashing-v1-d256"
    assert api.get("/api/evidence/index").json()["stale_documents"] == 1
    assert search(api, "chest pain")["hits"] == []  # old vectors are a different vector space: never mixed
    r = api.post("/api/evidence/index/rebuild")
    assert r.status_code == 202 and r.json()["documents_queued"] == 1
    st = idx_status(api, doc)
    assert not st["stale"] and st["index_model"] == "hashing-v1-d256"
    assert search(api, "chest pain")["hits"][0]["evidence"]["entity_name"] == "Chest pain"


def test_recover_interrupted_index(api, doc):
    set_columns(api, doc, index_status="processing")
    assert index_service.recover_interrupted_index(api.session_factory) == 1
    st = idx_status(api, doc)
    assert st["index_status"] == "failed" and st["error_code"] == "interrupted"


def test_concurrent_start_is_rejected(api, doc):
    set_columns(api, doc, index_status="processing")
    r = api.post(f"/api/documents/{doc}/evidence-index")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "processing_in_progress"


def test_document_with_no_evidence_indexes_to_zero(api):
    d = upload(api, factory.text_pdf([["Nothing clinical appears on this synthetic page at all."]], fontsize=9))
    process(api, d)
    st = idx_status(api, d)
    assert st["index_status"] == "completed" and st["indexed_count"] == 0


def test_stored_vectors_are_unit_length_and_text_is_reproducible(api, doc):
    import numpy as np
    from evidence_index import build_embedding_text
    from app.models.clinical_evidence import ClinicalEvidence
    with api.session_factory() as s:
        rows = s.execute(select(EvidenceEmbedding, ClinicalEvidence).join(ClinicalEvidence, ClinicalEvidence.id == EvidenceEmbedding.evidence_id)).all()
        assert rows
        for emb, ev in rows:
            assert abs(np.linalg.norm(np.frombuffer(emb.vector, dtype="<f4")) - 1) < 1e-4
            assert emb.embedding_text == build_embedding_text(ev) and emb.dimension == 512 and len(emb.text_sha256) == 64


def test_documents_api_exposes_index_fields(api, doc):
    d = api.get(f"/api/documents/{doc}").json()
    assert d["index_status"] == "completed" and d["indexed_count"] and d["index_model"] == "hashing-v1-d512"
