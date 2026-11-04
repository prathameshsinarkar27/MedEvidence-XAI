"""Phase 4 API tests: tables, images, source-page preview, multimodal processing status.

Run on SQLite and (if TEST_DATABASE_URL is set) PostgreSQL. All PDFs are synthetic.
"""

import hashlib
import io
import shutil
import uuid

import pytest
from PIL import Image
from sqlalchemy import update

from app.models.document import Document
from app.models.document_image import DocumentImage
from app.services import multimodal as mm
from app.services.multimodal import recover_interrupted_multimodal
from tests import pdf_factory as factory

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")


def upload(api, content: bytes, filename: str = "report.pdf") -> str:
    response = api.post("/api/documents", files={"file": (filename, content, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def process(api, doc_id: str) -> None:
    """Text processing; TestClient runs the background pipeline (text, then tables/images) before returning."""
    assert api.post(f"/api/documents/{doc_id}/process").status_code == 202


def multimodal(api, doc_id: str, query: str = "") -> dict:
    response = api.post(f"/api/documents/{doc_id}/multimodal{query}")
    assert response.status_code == 202, response.text
    assert response.json() == {"document_id": doc_id, "multimodal_status": "queued"}
    return api.get(f"/api/documents/{doc_id}/multimodal").json()


def status_of(api, doc_id: str) -> dict:
    return api.get(f"/api/documents/{doc_id}/multimodal").json()


def set_columns(api, doc_id: str, **values) -> None:
    with api.session_factory() as session:
        session.execute(update(Document).where(Document.id == uuid.UUID(doc_id)).values(**values))
        session.commit()


def tables(api, doc_id: str, query: str = "") -> list[dict]:
    return api.get(f"/api/documents/{doc_id}/tables{query}").json()["items"]


def images(api, doc_id: str, query: str = "") -> list[dict]:
    return api.get(f"/api/documents/{doc_id}/images{query}").json()["items"]


# ---------- before anything ran ----------


def test_new_upload_has_no_multimodal_results(api):
    doc_id = upload(api, factory.multimodal_pdf())
    status = status_of(api, doc_id)
    assert status["multimodal_status"] == "not_processed"
    assert status["table_count"] is None and status["image_count"] is None and status["pages_processed"] == 0
    assert tables(api, doc_id) == [] and images(api, doc_id) == []
    document = api.get(f"/api/documents/{doc_id}").json()
    assert document["multimodal_status"] == "not_processed" and document["table_count"] is None


# ---------- the automatic pipeline ----------


def test_processing_a_document_also_extracts_tables_and_images(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)

    status = status_of(api, doc_id)
    assert status["multimodal_status"] == "completed", status
    assert status["page_count"] == 2 and status["pages_processed"] == 2
    assert (status["table_count"], status["image_count"]) == (2, 2)
    assert status["images_by_status"] == {"extracted": 2}
    assert status["pages_with_tables"] == 1 and status["pages_with_images"] == 1
    assert status["error_code"] is None and status["processed_at"]
    assert status["summary"]["image_ocr_requested"] is False

    document = api.get(f"/api/documents/{doc_id}").json()
    assert document["processing_status"] == "completed"  # the text stage is independent
    assert (document["table_count"], document["image_count"]) == (2, 2)


def test_table_listing_and_detail_expose_structure_text_and_source_location(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)

    listing = tables(api, doc_id)
    assert [(t["page_number"], t["table_index"]) for t in listing] == [(1, 1), (1, 2)]
    first = listing[0]
    assert (first["row_count"], first["col_count"]) == (4, 4)
    assert first["detection_method"] == "pymupdf_find_tables"
    assert first["page_rotation"] == 0 and (first["page_width"], first["page_height"]) == (595.0, 842.0)
    assert (round(first["bbox"]["x0"]), round(first["bbox"]["y0"]), round(first["bbox"]["x1"]), round(first["bbox"]["y1"])) == (72, 110, 452, 206)
    region = first["region"]
    assert 0 <= region["x"] < 1 and 0 <= region["y"] < 1 and 0 < region["width"] <= 1 and 0 < region["height"] <= 1
    assert region["x"] == pytest.approx(72 / 595, abs=1e-3) and region["height"] == pytest.approx(96 / 842, abs=1e-3)
    assert "cells" not in first  # the list stays light

    detail = api.get(f"/api/documents/{doc_id}/tables/{first['id']}").json()
    assert detail["rows"] == factory.LAB_TABLE_ROWS
    assert len(detail["cells"]) == 16
    cell = next(c for c in detail["cells"] if (c["row_index"], c["col_index"]) == (1, 1))
    assert cell["text"] == "7.8" and cell["bbox"]["x1"] > cell["bbox"]["x0"]

    only_page_two = tables(api, doc_id, "?page_number=2")
    assert only_page_two == []


def test_image_listing_metadata_and_file_download(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)

    listing = images(api, doc_id)
    assert [(i["page_number"], i["image_index"]) for i in listing] == [(1, 1), (1, 2)]
    chart = listing[0]
    assert (chart["width_px"], chart["height_px"]) == (240, 140)
    assert chart["stored_format"] == "png" and chart["extraction_status"] == "extracted" and chart["has_file"]
    assert chart["is_full_page"] is False and chart["ocr_status"] == "not_requested"
    assert round(chart["bbox"]["x0"]) == 72 and round(chart["bbox"]["y1"]) == 390
    assert 0 <= chart["region"]["x"] < 1

    response = api.get(f"/api/documents/{doc_id}/images/{chart['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(response.content).hexdigest() == chart["sha256"]
    assert chart["file_size_bytes"] == len(response.content)
    with Image.open(io.BytesIO(response.content)) as decoded:
        assert decoded.size == (240, 140)

    detail = api.get(f"/api/documents/{doc_id}/images/{chart['id']}").json()
    assert detail["ocr_text"] is None and detail["id"] == chart["id"]
    assert images(api, doc_id, "?page_number=2") == []
    assert len(images(api, doc_id, "?page_number=1")) == 2


def test_extracted_image_files_live_in_the_configured_directory_only(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    files = sorted(p.name for p in (api.image_dir / doc_id).iterdir())
    assert len(files) == 2 and all(name.endswith(".png") for name in files)
    assert not list(api.upload_dir.glob("*.png"))


def test_auto_multimodal_can_be_switched_off_and_run_by_hand(api, configure):
    configure(AUTO_MULTIMODAL="false")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    assert api.get(f"/api/documents/{doc_id}").json()["processing_status"] == "completed"
    assert status_of(api, doc_id)["multimodal_status"] == "not_processed"

    status = multimodal(api, doc_id)
    assert status["multimodal_status"] == "completed" and status["table_count"] == 2


def test_multimodal_can_run_without_text_processing_first(api):
    doc_id = upload(api, factory.table_pdf())
    status = multimodal(api, doc_id)
    assert status["multimodal_status"] == "completed" and status["table_count"] == 1
    assert api.get(f"/api/documents/{doc_id}").json()["processing_status"] == "not_processed"


def test_running_again_replaces_rows_and_files(api):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    first_tables, first_images = tables(api, doc_id), images(api, doc_id)
    first_files = {p.name for p in (api.image_dir / doc_id).iterdir()}

    multimodal(api, doc_id)
    second_tables, second_images = tables(api, doc_id), images(api, doc_id)
    assert len(second_tables) == len(first_tables) == 2 and len(second_images) == len(first_images) == 2
    assert {t["id"] for t in first_tables}.isdisjoint(t["id"] for t in second_tables)
    second_files = {p.name for p in (api.image_dir / doc_id).iterdir()}
    assert len(second_files) == 2 and first_files.isdisjoint(second_files)  # old files were removed


def test_starting_while_a_run_is_in_progress_is_a_conflict(api):
    doc_id = upload(api, factory.table_pdf())
    for state in ("queued", "processing"):
        set_columns(api, doc_id, multimodal_status=state)
        response = api.post(f"/api/documents/{doc_id}/multimodal")
        assert response.status_code == 409 and response.json()["detail"]["code"] == "processing_in_progress"
    set_columns(api, doc_id, multimodal_status="failed")
    assert api.post(f"/api/documents/{doc_id}/multimodal").status_code == 202


def test_a_text_run_in_progress_does_not_block_multimodal(api):
    doc_id = upload(api, factory.table_pdf())
    set_columns(api, doc_id, processing_status="processing")
    assert multimodal(api, doc_id)["multimodal_status"] == "completed"


# ---------- unknown ids and validation ----------


def test_unknown_resources_return_404_with_codes(api):
    doc_id = upload(api, factory.table_pdf())
    missing = str(uuid.uuid4())
    cases = {
        f"/api/documents/{missing}/multimodal": "document_not_found",
        f"/api/documents/{missing}/tables": "document_not_found",
        f"/api/documents/{missing}/images": "document_not_found",
        f"/api/documents/{missing}/pages/1/preview": "document_not_found",
        f"/api/documents/{doc_id}/tables/{missing}": "table_not_found",
        f"/api/documents/{doc_id}/images/{missing}": "image_not_found",
        f"/api/documents/{doc_id}/images/{missing}/file": "image_not_found",
    }
    for url, code in cases.items():
        response = api.get(url)
        assert response.status_code == 404 and response.json()["detail"]["code"] == code, url
    assert api.post(f"/api/documents/{missing}/multimodal").status_code == 404


def test_malformed_ids_and_page_numbers_are_rejected(api):
    doc_id = upload(api, factory.table_pdf())
    assert api.get(f"/api/documents/{doc_id}/tables/not-a-uuid").status_code == 422
    assert api.get(f"/api/documents/{doc_id}/tables?page_number=0").status_code == 422
    assert api.get(f"/api/documents/{doc_id}/images?page_number=-1").status_code == 422
    assert api.get(f"/api/documents/{doc_id}/pages/0/preview").status_code == 422


def test_a_table_of_another_document_is_not_reachable(api):
    first = upload(api, factory.table_pdf())
    second = upload(api, factory.table_pdf())
    process(api, first)
    table_id = tables(api, first)[0]["id"]
    assert api.get(f"/api/documents/{second}/tables/{table_id}").status_code == 404


# ---------- source-page preview and source regions ----------


def test_page_preview_is_a_png_of_the_page(api):
    doc_id = upload(api, factory.table_pdf())
    response = api.get(f"/api/documents/{doc_id}/pages/1/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png" and response.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format == "PNG" and max(image.size) <= 1400 and image.height > image.width


def test_preview_errors_are_explicit(api):
    doc_id = upload(api, factory.table_pdf())
    response = api.get(f"/api/documents/{doc_id}/pages/9/preview")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "page_not_found"
    for file in api.upload_dir.glob("*.pdf"):
        file.unlink()
    response = api.get(f"/api/documents/{doc_id}/pages/1/preview")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "file_missing"


def _dark_extent_fraction(png: bytes, region: dict) -> tuple[float, float]:
    """Crop the preview to `region` and report how much of the crop the dark pixels span (1.0 = tight fit)."""
    with Image.open(io.BytesIO(png)) as image:
        gray = image.convert("L")
        w, h = gray.size
        pad = 3
        box = (round(region["x"] * w) - pad, round(region["y"] * h) - pad,
               round((region["x"] + region["width"]) * w) + pad, round((region["y"] + region["height"]) * h) + pad)
        crop = gray.crop(box)
        dark = crop.point(lambda v: 255 if v < 128 else 0).getbbox()
        assert dark is not None, "no dark pixels inside the reported region"
        return (dark[2] - dark[0]) / crop.width, (dark[3] - dark[1]) / crop.height


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_table_region_fits_the_rendered_preview_for_every_page_rotation(api, rotation):
    """End to end: stored box -> region fractions -> overlay on the rendered (rotated) page."""
    doc_id = upload(api, factory.table_pdf(rotation=rotation))
    process(api, doc_id)
    table = tables(api, doc_id)[0]
    assert table["page_rotation"] == rotation
    png = api.get(f"/api/documents/{doc_id}/pages/1/preview").content
    across, down = _dark_extent_fraction(png, table["region"])
    assert across > 0.93 and down > 0.9, (rotation, across, down)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_image_region_fits_the_rendered_preview_for_every_page_rotation(api, rotation):
    buffer = io.BytesIO()
    Image.new("RGB", (200, 120), (0, 0, 0)).save(buffer, "PNG")  # solid black block: easy to find
    doc_id = upload(api, factory.image_pdf([(buffer.getvalue(), (100, 200, 340, 344))], rotation=rotation))
    process(api, doc_id)
    image = images(api, doc_id)[0]
    png = api.get(f"/api/documents/{doc_id}/pages/1/preview").content
    across, down = _dark_extent_fraction(png, image["region"])
    assert across > 0.95 and down > 0.95, (rotation, across, down)


# ---------- optional OCR inside images ----------


def test_image_ocr_requested_without_tesseract_is_reported_not_silent(api, configure):
    configure(TESSERACT_CMD="/definitely/not/here/tesseract")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    assert status_of(api, doc_id)["multimodal_status"] == "completed"  # not requested: no OCR problems

    status = multimodal(api, doc_id, "?image_ocr=true")
    assert status["multimodal_status"] == "completed_with_errors" and status["error_code"] == "ocr_unavailable"
    assert "Tesseract" in status["error_message"] and status["summary"]["image_ocr_requested"] is True
    assert status["image_count"] == 2 and status["images_by_status"] == {"extracted": 2}  # images are still kept
    assert status["images_by_ocr_status"] == {"unavailable": 2}
    assert len(tables(api, doc_id)) == 2


@needs_tesseract
def test_image_ocr_reads_printed_text_when_requested(api):
    doc_id = upload(api, factory.image_pdf([(factory.text_image_png(["HEMOGLOBIN 7.8 PERCENT"], 30, 520), (60, 100, 460, 160))]))
    status = multimodal(api, doc_id, "?image_ocr=true")
    assert status["multimodal_status"] == "completed" and status["images_by_ocr_status"] == {"completed": 1}
    (summary,) = images(api, doc_id)
    assert summary["ocr_status"] == "completed" and summary["ocr_char_count"] > 10
    detail = api.get(f"/api/documents/{doc_id}/images/{summary['id']}").json()
    assert "hemoglobin" in detail["ocr_text"].lower() and detail["ocr_mean_confidence"] is not None


def test_image_ocr_setting_turns_it_on_by_default(api, configure):
    configure(IMAGE_OCR="true", TESSERACT_CMD="/definitely/not/here/tesseract")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    assert status_of(api, doc_id)["error_code"] == "ocr_unavailable"
    assert api.get("/api/processing/capabilities").json()["multimodal"]["image_ocr_default"] is True


# ---------- failures ----------


def test_corrupt_pdf_fails_text_stage_and_skips_the_automatic_multimodal_stage(api):
    doc_id = upload(api, b"%PDF-1.4\nthis is not a real pdf\n")
    process(api, doc_id)
    assert api.get(f"/api/documents/{doc_id}/processing").json()["processing_status"] == "failed"
    assert status_of(api, doc_id)["multimodal_status"] == "not_processed"

    status = multimodal(api, doc_id)  # explicit request: reported, with a code
    assert status["multimodal_status"] == "failed" and status["error_code"] == "invalid_pdf"
    assert tables(api, doc_id) == [] and images(api, doc_id) == []


def test_missing_stored_file_is_reported(api):
    doc_id = upload(api, factory.table_pdf())
    for file in api.upload_dir.glob("*.pdf"):
        file.unlink()
    status = multimodal(api, doc_id)
    assert status["multimodal_status"] == "failed" and status["error_code"] == "file_missing"


def test_encrypted_and_oversized_documents_fail_with_codes(api, configure):
    doc_id = upload(api, factory.encrypted_pdf())
    assert multimodal(api, doc_id)["error_code"] == "encrypted_pdf"
    configure(MAX_PDF_PAGES="2")
    many = upload(api, factory.blank_pdf(3))
    assert multimodal(api, many)["error_code"] == "too_many_pages"


def test_images_that_cannot_be_extracted_are_listed_with_a_reason(api, configure):
    configure(MAX_IMAGE_PIXELS="1000")
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    status = status_of(api, doc_id)
    assert status["multimodal_status"] == "completed_with_errors" and status["error_code"] == "image_errors"
    assert status["images_by_status"] == {"failed": 2} and status["table_count"] == 2
    failed = images(api, doc_id)[0]
    assert failed["extraction_status"] == "failed" and "MAX_IMAGE_PIXELS" in failed["error_message"]
    assert failed["has_file"] is False and failed["bbox"] is not None  # we still know where it is
    assert api.get(f"/api/documents/{doc_id}/images/{failed['id']}/file").status_code == 404


def test_tiny_images_and_limits_are_counted_in_the_summary(api, configure):
    configure(MAX_IMAGES_PER_DOCUMENT="1")
    tiny = factory.bar_chart_png(20, 20)
    chart = factory.bar_chart_png(120, 90)
    doc_id = upload(api, factory.image_pdf([(tiny, (10, 10, 30, 30)), (chart, (50, 100, 170, 190)), (chart, (50, 300, 170, 390))]))
    status = multimodal(api, doc_id)
    assert status["image_count"] == 1
    assert status["summary"]["images_skipped_small"] == 1 and status["summary"]["images_skipped_over_limit"] == 1


def test_unexpected_errors_end_in_failed_with_a_generic_message(api, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("secret internal detail /srv/path")

    monkeypatch.setattr(mm, "MultimodalProcessor", Boom)
    doc_id = upload(api, factory.table_pdf())
    status = multimodal(api, doc_id)
    assert status["multimodal_status"] == "failed" and status["error_code"] == "internal_error"
    assert "secret" not in status["error_message"] and "/srv" not in status["error_message"]


def test_a_page_that_cannot_be_saved_leaves_no_partial_results_and_others_continue(api, monkeypatch):
    real = mm._image_row
    calls = {"n": 0}

    def flaky(settings, document_id, image, written):
        calls["n"] += 1
        row = real(settings, document_id, image, written)  # file is written first, then we fail
        if calls["n"] == 2:
            raise RuntimeError("database write failed")
        return row

    monkeypatch.setattr(mm, "_image_row", flaky)
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    status = status_of(api, doc_id)
    assert status["multimodal_status"] == "completed_with_errors" and status["error_code"] == "page_errors"
    assert "could not be saved" in status["error_message"]
    assert tables(api, doc_id) == [] and images(api, doc_id) == []  # page 1 was all-or-nothing
    leftovers = list((api.image_dir / doc_id).glob("*")) if (api.image_dir / doc_id).exists() else []
    assert leftovers == []  # files written before the failure were removed
    assert status["pages_processed"] == 2


def test_interrupted_runs_are_marked_failed_at_startup_and_text_status_is_untouched(api):
    doc_id = upload(api, factory.table_pdf())
    process(api, doc_id)
    set_columns(api, doc_id, multimodal_status="processing")
    assert recover_interrupted_multimodal(api.session_factory) == 1
    status = status_of(api, doc_id)
    assert status["multimodal_status"] == "failed" and status["error_code"] == "interrupted"
    assert api.get(f"/api/documents/{doc_id}/processing").json()["processing_status"] == "completed"
    assert recover_interrupted_multimodal(api.session_factory) == 0


# ---------- file safety ----------


def test_a_tampered_stored_filename_cannot_read_files_outside_the_image_directory(api, tmp_path):
    doc_id = upload(api, factory.multimodal_pdf())
    process(api, doc_id)
    secret = tmp_path / "outside.png"
    secret.write_bytes(b"\x89PNG\r\n\x1a\nnot for you")
    image = images(api, doc_id)[0]
    for hostile in ("../../outside.png", "../outside.png", "/etc/passwd", "x.png", f"{uuid.uuid4()}.exe"):
        with api.session_factory() as session:
            session.execute(update(DocumentImage).where(DocumentImage.id == uuid.UUID(image["id"])).values(stored_filename=hostile))
            session.commit()
        response = api.get(f"/api/documents/{doc_id}/images/{image['id']}/file")
        assert response.status_code == 404 and response.json()["detail"]["code"] == "image_file_missing", hostile


def test_capabilities_describe_the_multimodal_engine_and_limits(api):
    body = api.get("/api/processing/capabilities").json()["multimodal"]
    assert body["table_engine"].startswith("PyMuPDF") and body["auto_multimodal"] is True
    assert body["image_ocr_default"] is False and body["min_image_side_px"] == 32
    assert body["max_images_per_document"] == 200 and body["max_tables_per_document"] == 500


def test_openapi_lists_the_new_routes(api):
    paths = api.get("/openapi.json").json()["paths"]
    for path in (
        "/api/documents/{document_id}/multimodal",
        "/api/documents/{document_id}/tables",
        "/api/documents/{document_id}/tables/{table_id}",
        "/api/documents/{document_id}/images",
        "/api/documents/{document_id}/images/{image_id}",
        "/api/documents/{document_id}/images/{image_id}/file",
        "/api/documents/{document_id}/pages/{page_number}/preview",
    ):
        assert path in paths, path
