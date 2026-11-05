"""Phase 5 API tests: clinical information extraction and the ClinicalEvidence model.

Run on SQLite and (if TEST_DATABASE_URL is set) PostgreSQL. All PDFs and text are synthetic.
"""

import shutil
import uuid

import pytest
from sqlalchemy import select, update

from app.models.clinical_evidence import ClinicalEvidence
from app.models.document import Document
from app.services.clinical import recover_interrupted_clinical
from tests import pdf_factory as factory

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")

NARRATIVE = [
    "SYNTHETIC CLINIC NOTE - NOT A REAL PATIENT",
    "Report date: 12-Aug-2026",
    "Patient denies chest pain or fever. History of type 2 diabetes mellitus.",
    "Mother had hypertension. Allergic to penicillin.",
    "Metformin 500 mg twice daily PO. BP 140/90 mmHg.",
    "HbA1c was 7.8 % on 12-Aug-2026.",
]


def narrative_pdf() -> bytes:
    return factory.text_pdf([NARRATIVE], fontsize=9)  # small font: long lines must not run off the page


def upload(api, content: bytes) -> str:
    response = api.post("/api/documents", files={"file": ("report.pdf", content, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def process(api, doc_id: str) -> None:
    """TestClient runs the whole background pipeline (text, tables/images, clinical) before returning."""
    assert api.post(f"/api/documents/{doc_id}/process").status_code == 202


def clinical_status(api, doc_id: str) -> dict:
    return api.get(f"/api/documents/{doc_id}/clinical-extraction").json()


def evidence(api, doc_id: str, query: str = "") -> list[dict]:
    response = api.get(f"/api/documents/{doc_id}/clinical-evidence{query}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def by_name(items: list[dict], name: str) -> list[dict]:
    return [i for i in items if i["entity_name"] == name]


def set_columns(api, doc_id: str, **values) -> None:
    with api.session_factory() as session:
        session.execute(update(Document).where(Document.id == uuid.UUID(doc_id)).values(**values))
        session.commit()


# ---------- before anything ran ----------
def test_nothing_before_processing(api):
    doc_id = upload(api, narrative_pdf())
    body = clinical_status(api, doc_id)
    assert body["clinical_status"] == "not_processed" and body["evidence_count"] is None
    assert body["by_entity_type"] == {} and "Not yet evaluated" in body["note"]
    assert evidence(api, doc_id) == []


def test_manual_start_requires_text_processing(api):
    doc_id = upload(api, narrative_pdf())
    response = api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "text_not_processed"


def test_unknown_document_and_evidence_are_404(api):
    missing = uuid.uuid4()
    for method, path in [("get", f"/api/documents/{missing}/clinical-extraction"),
                         ("post", f"/api/documents/{missing}/clinical-extraction"),
                         ("get", f"/api/documents/{missing}/clinical-evidence"),
                         ("get", f"/api/documents/{missing}/clinical-evidence/{missing}")]:
        response = getattr(api, method)(path)
        assert response.status_code == 404 and response.json()["detail"]["code"] == "document_not_found", path
    doc_id = upload(api, narrative_pdf())
    response = api.get(f"/api/documents/{doc_id}/clinical-evidence/{missing}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "evidence_not_found"


# ---------- text extraction, end to end ----------
def test_pipeline_extracts_evidence_automatically_with_traceability(api):
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    status = clinical_status(api, doc_id)
    assert status["clinical_status"] == "completed" and status["evidence_count"] == len(evidence(api, doc_id))
    assert status["pages_processed"] == status["page_count"] == 1
    assert {"lab_result", "vital_sign", "medication", "condition", "symptom", "date"} <= set(status["by_entity_type"])
    assert status["extractor_version"] == "5.0.0" and status["summary"]["page_regions_available"] is True

    page_text = api.get(f"/api/documents/{doc_id}/pages/1").json()["extracted_text"]
    items = evidence(api, doc_id)
    assert [i["ordinal"] if "ordinal" in i else 0 for i in items]  # list is ordered, ordinal is internal
    for item in items:
        assert item["document_id"] == doc_id and item["page_number"] == 1 and item["modality"] == "text"
        # exact source: the stored page text, sliced with the stored offsets, is the stored mention
        assert page_text[item["char_start"]:item["char_end"]] == item["mention_text"]
        assert page_text[item["source_start"]:item["source_end"]] == item["source_text"]
        assert 0 < item["extraction_confidence"] <= 0.99 and "base" in item["confidence_factors"]
        assert item["extractor_version"] == "5.0.0"
        # located on the page
        region = item["region"]
        assert region and 0 <= region["x"] <= 1 and 0 <= region["y"] <= 1 and region["width"] > 0
        assert "verification_status" not in item  # verification belongs to Phase 8

    hba1c = by_name(items, "Hemoglobin A1c")[0]
    assert (hba1c["entity_type"], hba1c["value_text"], hba1c["unit_normalized"], hba1c["date_iso"]) == ("lab_result", "7.8", "%", "2026-08-12")
    assert by_name(items, "Chest pain")[0]["assertion"] == "negated"
    assert by_name(items, "Hypertension")[0]["assertion"] == "family_history"
    assert by_name(items, "Penicillin")[0]["assertion"] == "allergy"
    metformin = by_name(items, "Metformin")[0]
    assert metformin["attributes"]["times_per_day"] == 2 and metformin["unit_normalized"] == "mg"
    bp = by_name(items, "Blood pressure")[0]
    assert bp["attributes"] == {"systolic": 140, "diastolic": 90}
    detail = api.get(f"/api/documents/{doc_id}/clinical-evidence/{hba1c['evidence_id']}")
    assert detail.status_code == 200 and detail.json() == hba1c


def test_filters_pagination_and_validation(api):
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    everything = evidence(api, doc_id)
    labs = evidence(api, doc_id, "?entity_type=lab_result")
    assert labs and all(i["entity_type"] == "lab_result" for i in labs)
    negated = evidence(api, doc_id, "?assertion=negated")
    assert {i["entity_name"] for i in negated} == {"Chest pain", "Fever"}
    assert evidence(api, doc_id, "?page_number=2") == []
    assert evidence(api, doc_id, "?modality=table") == []
    high = evidence(api, doc_id, "?min_confidence=0.95")
    assert len(high) < len(everything)
    page = api.get(f"/api/documents/{doc_id}/clinical-evidence?limit=3&offset=2").json()
    assert page["total"] == len(everything) and [i["evidence_id"] for i in page["items"]] == [i["evidence_id"] for i in everything[2:5]]
    for bad in ("?entity_type=banana", "?assertion=maybe", "?limit=0", "?limit=5000", "?min_confidence=2", "?page_number=0"):
        assert api.get(f"/api/documents/{doc_id}/clinical-evidence{bad}").status_code == 422, bad


# ---------- tables and images ----------
def test_table_rows_are_extracted_once_with_cell_provenance(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    items = evidence(api, doc_id)
    hba1c = by_name(items, "Hemoglobin A1c")
    assert len(hba1c) == 1 and hba1c[0]["modality"] == "table"  # the text-layer copy of the table row is suppressed
    row = hba1c[0]
    assert row["table_id"] and row["table_row_index"] == 1 and row["cell_positions"] == [[1, 0], [1, 1], [1, 2], [1, 3]]
    assert row["source_text"] == "Hemoglobin A1c | 7.8 | % | 4.0 - 5.6" and row["char_start"] is None
    assert (row["abnormal_flag"], row["flag_source"]) == ("high", "printed_reference_range")
    assert row["region"] and row["extraction_method"] == "rule_lab_table_columns_v1"
    table = api.get(f"/api/documents/{doc_id}/tables/{row['table_id']}").json()
    assert table["rows"][1][0] == "Hemoglobin A1c"  # traceable back to the Phase 4 table
    assert {i["entity_name"] for i in items if i["entity_type"] == "lab_result"} == {"Hemoglobin A1c", "Fasting glucose", "Sodium"}
    meds = [i for i in items if i["entity_type"] == "medication"]
    assert {m["entity_name"] for m in meds} == {"Metformin", "Amlodipine", "Atorvastatin"} and len(meds) == 3
    assert clinical_status(api, doc_id)["summary"]["text_duplicates_of_table_rows_suppressed"] >= 3


def test_without_table_extraction_the_text_layer_still_yields_the_rows(api, configure):
    configure(AUTO_MULTIMODAL="false")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    items = evidence(api, doc_id)
    assert by_name(items, "Hemoglobin A1c") and all(i["modality"] == "text" for i in items)


@needs_tesseract
def test_image_ocr_text_yields_image_evidence(api, configure):
    configure(IMAGE_OCR="true")
    picture = factory.text_image_png(["HbA1c 7.8 %", "Glucose 110 mg/dL"], fontsize=22, width=360)
    doc_id = upload(api, factory.image_pdf([(picture, (72, 120, 360, 220))]))
    process(api, doc_id)
    items = evidence(api, doc_id, "?modality=image_ocr")
    assert {i["entity_name"] for i in items} >= {"Hemoglobin A1c"}
    assert all(i["image_id"] and i["source_field"] == "image_ocr_text" and i["ocr_confidence"] is not None for i in items)
    assert all(i["region"] and i["char_start"] is not None for i in items)  # located by the image's box
    image = api.get(f"/api/documents/{doc_id}/images/{items[0]['image_id']}").json()
    assert image["page_number"] == items[0]["page_number"]
    assert image["ocr_text"][items[0]["char_start"]:items[0]["char_end"]] == items[0]["mention_text"]


@needs_tesseract
def test_scanned_page_evidence_is_ocr_with_lower_confidence(api):
    scanned = factory.scanned_pdf([factory.LAB_REPORT_LINES])
    doc_id = upload(api, scanned)
    process(api, doc_id)
    items = evidence(api, doc_id)
    assert items and all(i["modality"] == "ocr" for i in items)
    assert all(i["region"] is None for i in items)  # OCR text has no stored word boxes
    assert all("ocr_text_reliability_multiplier" in i["confidence_factors"] and i["ocr_confidence"] is not None for i in items)


def test_rotated_page_regions_stay_inside_the_displayed_page(api):
    doc_id = upload(api, factory.table_pdf(rotation=90))
    process(api, doc_id)
    items = [i for i in evidence(api, doc_id) if i["region"]]
    assert items
    for i in items:
        r = i["region"]
        assert i["page_rotation"] == 90
        assert 0 <= r["x"] and r["x"] + r["width"] <= 1.0001 and 0 <= r["y"] and r["y"] + r["height"] <= 1.0001


# ---------- lifecycle ----------
def test_auto_extraction_can_be_turned_off_and_run_manually(api, configure):
    configure(AUTO_CLINICAL_EXTRACTION="false")
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    assert clinical_status(api, doc_id)["clinical_status"] == "not_processed"
    response = api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert response.status_code == 202 and response.json() == {"document_id": doc_id, "clinical_status": "queued"}
    first = evidence(api, doc_id)
    assert clinical_status(api, doc_id)["clinical_status"] == "completed" and first
    api.post(f"/api/documents/{doc_id}/clinical-extraction")  # run again: replaced, not duplicated
    second = evidence(api, doc_id)
    assert len(second) == len(first) and {i["evidence_id"] for i in second}.isdisjoint({i["evidence_id"] for i in first})


def test_double_start_is_a_409(api, configure):
    configure(AUTO_CLINICAL_EXTRACTION="false")
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    set_columns(api, doc_id, clinical_status="processing")
    response = api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "processing_in_progress"


def test_reprocessing_text_or_tables_discards_stale_evidence(api, configure):
    configure(AUTO_CLINICAL_EXTRACTION="false")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert evidence(api, doc_id)
    api.post(f"/api/documents/{doc_id}/multimodal")  # tables are regenerated -> evidence pointing at them is stale
    assert evidence(api, doc_id) == [] and clinical_status(api, doc_id)["clinical_status"] == "not_processed"
    api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert evidence(api, doc_id)
    process(api, doc_id)  # text is regenerated
    assert evidence(api, doc_id) == [] and clinical_status(api, doc_id)["evidence_count"] is None


def test_failed_text_processing_skips_clinical_extraction(api):
    doc_id = upload(api, narrative_pdf())
    with api.session_factory() as session:  # simulate: text processing failed
        session.execute(update(Document).where(Document.id == uuid.UUID(doc_id)).values(processing_status="failed"))
        session.commit()
    response = api.post(f"/api/documents/{doc_id}/clinical-extraction")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "text_not_processed"


def test_interrupted_runs_are_marked_failed_at_startup(api):
    doc_id = upload(api, narrative_pdf())
    set_columns(api, doc_id, clinical_status="processing")
    assert recover_interrupted_clinical(api.session_factory) == 1
    body = clinical_status(api, doc_id)
    assert body["clinical_status"] == "failed" and body["error_code"] == "interrupted"
    assert recover_interrupted_clinical(api.session_factory) == 0


def test_blank_document_completes_with_no_evidence(api):
    doc_id = upload(api, factory.blank_pdf(2))
    process(api, doc_id)
    body = clinical_status(api, doc_id)
    assert body["clinical_status"] == "completed" and body["evidence_count"] == 0 and body["pages_processed"] == 2


def test_evidence_limit_is_enforced_and_reported(api, configure):
    configure(MAX_EVIDENCE_PER_DOCUMENT="10")
    lines = [f"Sodium {130 + i} mmol/L" for i in range(15)]
    doc_id = upload(api, factory.text_pdf([lines]))
    process(api, doc_id)
    body = clinical_status(api, doc_id)
    assert body["evidence_count"] == 10 and len(evidence(api, doc_id)) == 10
    assert body["clinical_status"] == "completed_with_errors" and body["error_code"] == "evidence_limit_reached"


def test_page_failure_is_isolated(api, monkeypatch):
    from app.services import clinical

    real = clinical.extract_text_evidence

    def flaky(text, modality="text", ocr_confidence=None):
        if "BOOM" in text:
            raise RuntimeError("synthetic failure")
        return real(text, modality, ocr_confidence)

    monkeypatch.setattr(clinical, "extract_text_evidence", flaky)
    doc_id = upload(api, factory.text_pdf([["BOOM page"], ["HbA1c 7.8 % on 12-Aug-2026"]]))
    process(api, doc_id)
    body = clinical_status(api, doc_id)
    assert body["clinical_status"] == "completed_with_errors" and body["error_code"] == "page_errors"
    assert "synthetic failure" not in (body["error_message"] or "")  # internal details are not exposed
    assert {i["page_number"] for i in evidence(api, doc_id)} == {2}


def test_deleting_the_stored_pdf_still_allows_extraction_without_regions(api, configure):
    configure(AUTO_CLINICAL_EXTRACTION="false")
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    for file in api.upload_dir.rglob("*.pdf"):
        file.unlink()
    assert api.post(f"/api/documents/{doc_id}/clinical-extraction").status_code == 202
    items = evidence(api, doc_id)
    assert items and all(i["region"] is None for i in items)
    assert clinical_status(api, doc_id)["summary"]["page_regions_available"] is False


def test_capabilities_describe_the_clinical_extractor(api):
    body = api.get("/api/processing/capabilities").json()["clinical"]
    assert body["extractor_version"] == "5.0.0" and "No trained model" in body["approach"]
    assert body["lexicon_sizes"]["lab_tests"] >= 30
    assert "lab_result" in body["entity_types"] and "negated" in body["assertions"]


def test_evidence_rows_are_deleted_with_their_document(api):
    doc_id = upload(api, narrative_pdf())
    process(api, doc_id)
    with api.session_factory() as session:
        assert session.scalars(select(ClinicalEvidence).where(ClinicalEvidence.document_id == uuid.UUID(doc_id))).first()


def test_sample_clinical_note_end_to_end(api):
    doc_id = upload(api, factory.clinical_note_pdf())
    process(api, doc_id)
    items = evidence(api, doc_id)
    got = {(i["entity_name"], i["assertion"]) for i in items}
    assert {("Chest pain", "negated"), ("Fever", "negated"), ("Peripheral neuropathy", "uncertain"),
            ("Hypertension", "family_history"), ("Penicillin", "allergy"), ("Aspirin", "discontinued"),
            ("Metformin", "affirmed"), ("Amlodipine", "affirmed"), ("Heart rate", "affirmed")} <= got
    assert {i["modality"] for i in items} == {"text", "table"}
    dates = {i["date_text"]: i["date_iso"] for i in items if i["entity_type"] == "date"}
    assert dates["12-Aug-2026"] == "2026-08-12" and dates["03/09/2026"] is None  # ambiguous: never guessed
