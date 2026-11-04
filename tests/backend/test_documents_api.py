"""API tests for upload/list/metadata. Run on SQLite and, when configured, real PostgreSQL."""

import hashlib
import uuid
from datetime import datetime

# NOTE: these are minimal fake PDFs: they carry the "%PDF-" signature but are not parsed.
# Real PDF parsing arrives in Phase 3.


def pdf_bytes(payload: bytes = b"synthetic content") -> bytes:
    return b"%PDF-1.4\n" + payload + b"\n%%EOF\n"


def upload(api, content=None, filename="report.pdf", content_type="application/pdf"):
    content = pdf_bytes() if content is None else content
    return api.post("/api/documents", files={"file": (filename, content, content_type)})


def stored_files(api):
    return sorted(p.name for p in api.upload_dir.glob("*")) if api.upload_dir.exists() else []


def test_upload_success_returns_metadata_and_stores_file(api):
    content = pdf_bytes(b"hello")
    response = upload(api, content, filename="Lab Report.pdf")
    assert response.status_code == 201
    body = response.json()

    doc_id = uuid.UUID(body["id"])
    assert body["original_filename"] == "Lab Report.pdf"
    assert body["file_type"] == "pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["file_size_bytes"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["upload_status"] == "uploaded"
    assert body["uploaded_at"]
    assert body["storage_path"] == f"{doc_id}.pdf"
    assert "/" not in body["storage_path"]  # relative, never an absolute server path

    assert stored_files(api) == [f"{doc_id}.pdf"]
    assert (api.upload_dir / f"{doc_id}.pdf").read_bytes() == content


def test_client_filename_never_controls_storage_location(api):
    response = upload(api, filename="../../../etc/passwd.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "passwd.pdf"
    assert stored_files(api) == [f"{body['id']}.pdf"]


def test_duplicate_content_gets_distinct_documents(api):
    first = upload(api).json()
    second = upload(api).json()
    assert first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]
    assert len(stored_files(api)) == 2


def test_list_documents_newest_first_with_pagination(api):
    ids = [upload(api, pdf_bytes(str(i).encode()), filename=f"d{i}.pdf").json()["id"] for i in range(3)]

    body = api.get("/api/documents").json()
    assert body["total"] == 3
    assert [d["id"] for d in body["items"]] == ids[::-1]

    page = api.get("/api/documents", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 3 and page["limit"] == 2 and page["offset"] == 1
    assert [d["id"] for d in page["items"]] == ids[::-1][1:3]


def test_list_empty(api):
    assert api.get("/api/documents").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_rejects_bad_pagination(api):
    assert api.get("/api/documents", params={"limit": 0}).status_code == 422
    assert api.get("/api/documents", params={"limit": 1000}).status_code == 422
    assert api.get("/api/documents", params={"offset": -1}).status_code == 422


def test_get_document_metadata(api):
    created = upload(api).json()
    response = api.get(f"/api/documents/{created['id']}")
    assert response.status_code == 200
    fetched = response.json()

    # SQLite does not store time zones, so compare the instant ignoring tzinfo (PostgreSQL keeps it).
    def instant(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)

    assert instant(fetched.pop("uploaded_at")) == instant(created.pop("uploaded_at"))
    assert fetched == created


def test_get_unknown_document_404(api):
    response = api.get(f"/api/documents/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"


def test_get_invalid_id_422(api):
    assert api.get("/api/documents/not-a-uuid").status_code == 422


def test_upload_policy(api):
    body = api.get("/api/documents/upload-policy").json()
    assert body["allowed_extensions"] == [".pdf"]
    assert body["allowed_mime_types"] == ["application/pdf"]
    assert body["max_upload_size_bytes"] == 1024 * 1024
    assert body["accepted_file_type"] == "PDF"


# ---- rejections: each must leave no file and no database row behind ----


def assert_nothing_persisted(api):
    assert stored_files(api) == []
    assert api.get("/api/documents").json()["total"] == 0


def test_reject_wrong_extension(api):
    for name in ["notes.txt", "run.exe", "archive.zip", "evil.pdf.exe", "noext"]:
        response = upload(api, filename=name)
        assert response.status_code == 415, name
        assert response.json()["detail"]["code"] == "unsupported_extension"
    assert_nothing_persisted(api)


def test_reject_wrong_content_type(api):
    for ct in ["text/plain", "application/octet-stream", "application/x-msdownload"]:
        response = upload(api, content_type=ct)
        assert response.status_code == 415, ct
        assert response.json()["detail"]["code"] == "unsupported_content_type"
    assert_nothing_persisted(api)


def test_reject_executable_disguised_as_pdf(api):
    response = upload(api, b"MZ\x90\x00\x03\x00\x00\x00 fake windows executable", filename="invoice.pdf")
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "invalid_pdf_signature"
    assert_nothing_persisted(api)


def test_reject_empty_file(api):
    response = upload(api, b"")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "file_empty"
    assert_nothing_persisted(api)


def test_reject_file_over_limit_without_leaving_partial_file(api):
    # 1 MB limit; stay under the early Content-Length guard so the streaming check is exercised.
    response = upload(api, pdf_bytes(b"x" * (1024 * 1024 + 10)))
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert_nothing_persisted(api)
    assert not list(api.upload_dir.glob(".incoming-*"))


def test_file_exactly_at_limit_is_accepted(api):
    header, footer = b"%PDF-1.4\n", b"\n%%EOF\n"
    content = header + b"x" * (1024 * 1024 - len(header) - len(footer)) + footer
    assert len(content) == 1024 * 1024
    assert upload(api, content).status_code == 201


def test_early_content_length_rejection(api):
    # Declared size far above limit + multipart allowance is refused before the body is parsed.
    response = upload(api, b"%PDF-" + b"x" * (3 * 1024 * 1024))
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert_nothing_persisted(api)


def test_missing_file_field_422(api):
    assert api.post("/api/documents").status_code == 422
    assert api.post("/api/documents", data={"other": "x"}).status_code == 422


def test_database_failure_removes_stored_file(api, monkeypatch):
    def boom(self):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", boom)
    response = upload(api)
    assert response.status_code == 500
    assert stored_files(api) == []


def test_documents_unavailable_without_database(client):
    response = client.get("/api/documents")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_not_configured"
