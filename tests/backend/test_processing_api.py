"""Phase 3 API tests: processing, status, pages, capabilities. Run on SQLite and (if configured) PostgreSQL."""

import shutil
import uuid

import pymupdf
import pytest
from sqlalchemy import update

from app.models.document import Document
from app.services.processing import recover_interrupted
from tests import pdf_factory as factory

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")

TEXT_PAGES = [
    ["Page one of a synthetic report: Hemoglobin A1c 7.8 % on 12-Aug-2026."],
    ["Page two of a synthetic report: Fasting glucose 110 mg/dL, units µg/dL and 37 °C."],
]


def upload(api, content: bytes, filename: str = "report.pdf") -> str:
    response = api.post("/api/documents", files={"file": (filename, content, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def process(api, doc_id: str) -> dict:
    response = api.post(f"/api/documents/{doc_id}/process")
    assert response.status_code == 202, response.text
    assert response.json() == {"document_id": doc_id, "processing_status": "queued"}
    # TestClient runs background tasks before returning, so processing has finished.
    status = api.get(f"/api/documents/{doc_id}/processing")
    assert status.status_code == 200
    return status.json()


def set_status(api, doc_id: str, status: str) -> None:
    with api.session_factory() as session:
        session.execute(update(Document).where(Document.id == uuid.UUID(doc_id)).values(processing_status=status))
        session.commit()


# ---------- before processing ----------


def test_new_upload_reports_not_processed(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    document = api.get(f"/api/documents/{doc_id}").json()
    assert document["processing_status"] == "not_processed"
    assert document["page_count"] is None and document["processed_at"] is None
    status = api.get(f"/api/documents/{doc_id}/processing").json()
    assert status["processing_status"] == "not_processed"
    assert status["pages_processed"] == 0 and status["pages_by_method"] == {}
    assert api.get(f"/api/documents/{doc_id}/pages").json()["items"] == []


# ---------- text PDFs ----------


def test_process_text_pdf_end_to_end(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES, title="Synthetic Title"))
    status = process(api, doc_id)

    assert status["processing_status"] == "completed"
    assert status["page_count"] == 2 and status["pages_processed"] == 2
    assert status["pages_by_method"] == {"pymupdf": 2}
    assert status["pages_by_status"] == {"completed": 2}
    assert status["pages_by_ocr_status"] == {"not_needed": 2}
    assert status["likely_scanned_pages"] == 0
    assert status["error_code"] is None and status["error_message"] is None
    assert status["processed_at"]

    document = api.get(f"/api/documents/{doc_id}").json()
    assert document["processing_status"] == "completed" and document["page_count"] == 2
    assert document["pdf_metadata"]["title"] == "Synthetic Title"
    assert document["pdf_metadata"]["format"].startswith("PDF")

    listing = api.get(f"/api/documents/{doc_id}/pages").json()
    assert listing["page_count"] == 2
    assert [p["page_number"] for p in listing["items"]] == [1, 2]
    assert all("extracted_text" not in p for p in listing["items"])  # summaries carry no text
    assert listing["items"][0]["document_id"] == doc_id and listing["items"][0]["id"]

    page1 = api.get(f"/api/documents/{doc_id}/pages/1").json()
    assert "Hemoglobin A1c 7.8" in page1["extracted_text"]
    assert page1["extraction_method"] == "pymupdf" and page1["processing_status"] == "completed"
    assert page1["char_count"] > 0 and page1["ocr_status"] == "not_needed"
    assert "Fasting glucose" in api.get(f"/api/documents/{doc_id}/pages/2").json()["extracted_text"]


def test_stored_text_equals_parser_output_exactly(api):
    content = factory.text_pdf(TEXT_PAGES)
    doc_id = upload(api, content)
    process(api, doc_id)
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        expected = [page.get_text("text") for page in pdf]
    stored = [api.get(f"/api/documents/{doc_id}/pages/{n}").json()["extracted_text"] for n in (1, 2)]
    assert stored == expected  # original text preserved: no trimming, reflow or normalisation


def test_page_endpoints_validate_and_404(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    process(api, doc_id)
    assert api.get(f"/api/documents/{doc_id}/pages/3").status_code == 404
    assert api.get(f"/api/documents/{doc_id}/pages/3").json()["detail"]["code"] == "page_not_found"
    assert api.get(f"/api/documents/{doc_id}/pages/0").status_code == 422
    assert api.get(f"/api/documents/{doc_id}/pages/abc").status_code == 422
    unknown = uuid.uuid4()
    for url in ("processing", "pages", "pages/1"):
        response = api.get(f"/api/documents/{unknown}/{url}")
        assert response.status_code == 404 and response.json()["detail"]["code"] == "document_not_found"
    assert api.post(f"/api/documents/{unknown}/process").status_code == 404
    assert api.post("/api/documents/not-a-uuid/process").status_code == 422


def test_reprocessing_replaces_pages_instead_of_duplicating(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    process(api, doc_id)
    first_ids = {p["id"] for p in api.get(f"/api/documents/{doc_id}/pages").json()["items"]}
    status = process(api, doc_id)
    second = api.get(f"/api/documents/{doc_id}/pages").json()["items"]
    assert status["pages_processed"] == 2 and len(second) == 2
    assert not first_ids & {p["id"] for p in second}


def test_cannot_start_processing_twice_at_once(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    for busy in ("queued", "processing"):
        set_status(api, doc_id, busy)
        response = api.post(f"/api/documents/{doc_id}/process")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "processing_in_progress"
    set_status(api, doc_id, "failed")
    assert api.post(f"/api/documents/{doc_id}/process").status_code == 202  # terminal states can be re-run


# ---------- scanned PDFs and OCR availability ----------


def test_scanned_pdf_without_tesseract_reports_clear_setup_error(api, configure):
    configure(TESSERACT_CMD="/definitely/not/here/tesseract")
    doc_id = upload(api, factory.mixed_pdf(factory.LAB_REPORT_LINES, ["Scanned line of text"]))
    status = process(api, doc_id)

    assert status["processing_status"] == "completed_with_errors"
    assert status["error_code"] == "ocr_unavailable"
    assert "Tesseract OCR was not found" in status["error_message"]
    assert "TESSERACT_CMD" in status["error_message"]
    assert status["pages_by_status"] == {"completed": 1, "needs_ocr": 1}
    assert status["pages_by_ocr_status"] == {"not_needed": 1, "unavailable": 1}
    assert status["likely_scanned_pages"] == 1

    pages = api.get(f"/api/documents/{doc_id}/pages").json()["items"]
    assert pages[0]["processing_status"] == "completed"  # the text page was still extracted
    assert pages[1]["processing_status"] == "needs_ocr" and "Install" in pages[1]["error_message"]
    assert api.get(f"/api/documents/{doc_id}/pages/2").json()["extracted_text"] == ""


def test_scanned_only_pdf_without_tesseract_is_failed_not_silent(api, configure):
    configure(TESSERACT_CMD="/definitely/not/here/tesseract")
    status = process(api, upload(api, factory.scanned_pdf([["Only a scan"]])))
    # needs_ocr pages are not "failed", but the document must not look healthy.
    assert status["processing_status"] == "completed_with_errors"
    assert status["error_code"] == "ocr_unavailable"


@needs_tesseract
def test_scanned_pdf_is_ocrd_with_real_tesseract(api):
    doc_id = upload(api, factory.scanned_pdf([["Hemoglobin A1c 7.8 percent", "Fasting glucose 110 mg/dL"]]))
    status = process(api, doc_id)
    assert status["processing_status"] == "completed" and status["error_code"] is None
    assert status["pages_by_method"] == {"ocr_tesseract": 1}
    assert status["pages_by_ocr_status"] == {"completed": 1}
    assert status["likely_scanned_pages"] == 1
    page = api.get(f"/api/documents/{doc_id}/pages/1").json()
    assert "hemoglobin" in page["extracted_text"].lower()
    assert page["is_likely_scanned"] and page["has_images"]
    assert page["ocr_mean_confidence"] is not None


# ---------- documents that cannot be processed ----------


@pytest.mark.parametrize(
    "content, code",
    [
        (b"%PDF-1.4\nthis is only a header, not a document\n", "invalid_pdf"),  # passes the Phase 2 signature check
        (factory.encrypted_pdf(), "encrypted_pdf"),
    ],
)
def test_unprocessable_pdfs_end_failed_with_reason(api, content, code):
    doc_id = upload(api, content)
    status = process(api, doc_id)
    assert status["processing_status"] == "failed"
    assert status["error_code"] == code and status["error_message"]
    assert status["pages_processed"] == 0
    document = api.get(f"/api/documents/{doc_id}").json()
    assert document["processing_status"] == "failed" and document["processing_error_code"] == code


def test_page_limit_is_enforced(api, configure):
    configure(MAX_PDF_PAGES="1")
    status = process(api, upload(api, factory.blank_pdf(2)))
    assert status["processing_status"] == "failed" and status["error_code"] == "too_many_pages"


def test_missing_stored_file_is_reported(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    (api.upload_dir / f"{doc_id}.pdf").unlink()
    status = process(api, doc_id)
    assert status["processing_status"] == "failed" and status["error_code"] == "file_missing"


def test_failed_reprocess_clears_old_pages(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    process(api, doc_id)
    (api.upload_dir / f"{doc_id}.pdf").write_bytes(b"%PDF-1.4 now corrupt")
    status = process(api, doc_id)
    assert status["processing_status"] == "failed" and status["pages_processed"] == 0
    assert api.get(f"/api/documents/{doc_id}").json()["page_count"] is None


def test_interrupted_processing_is_recovered_as_failed(api):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))
    set_status(api, doc_id, "processing")
    assert recover_interrupted(api.session_factory) == 1
    status = api.get(f"/api/documents/{doc_id}/processing").json()
    assert status["processing_status"] == "failed" and status["error_code"] == "interrupted"
    assert recover_interrupted(api.session_factory) == 0


def test_unexpected_error_leaves_a_terminal_status(api, monkeypatch):
    doc_id = upload(api, factory.text_pdf(TEXT_PAGES))

    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.services.processing.PdfProcessor", explode)
    status = process(api, doc_id)
    assert status["processing_status"] == "failed" and status["error_code"] == "internal_error"
    assert "secret internal detail" not in status["error_message"]  # internals are logged, not returned


# ---------- capabilities ----------


def test_capabilities_reports_engine_and_settings(api):
    body = api.get("/api/processing/capabilities").json()
    assert body["pdf_engine"].startswith("PyMuPDF")
    assert isinstance(body["ocr"]["available"], bool)
    assert body["ocr"]["requested_languages"] == ["eng"]
    assert body["min_text_chars_per_page"] == 25 and body["max_pdf_pages"] == 300


def test_capabilities_explains_missing_tesseract(api, configure):
    configure(TESSERACT_CMD="/definitely/not/here/tesseract")
    ocr = api.get("/api/processing/capabilities").json()["ocr"]
    assert ocr["available"] is False and ocr["version"] is None
    assert "Install Tesseract" in ocr["message"]


@needs_tesseract
def test_capabilities_with_real_tesseract(api):
    ocr = api.get("/api/processing/capabilities").json()["ocr"]
    assert ocr["available"] is True and ocr["version"] and "eng" in ocr["installed_languages"]


# ---------- settings validation ----------


@pytest.mark.parametrize("value", ["eng; rm -rf /", "eng+", "+eng", "eng hin", ""])
def test_ocr_languages_setting_is_validated(monkeypatch, value):
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("OCR_LANGUAGES", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_ocr_languages_accepts_combinations(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("OCR_LANGUAGES", "eng+hin")
    assert Settings(_env_file=None).processing_config.ocr_languages == "eng+hin"
