"""Phase 4 library tests: table detection, image extraction, geometry, page rendering.

Everything runs on SYNTHETIC PDFs built by tests/pdf_factory.py. These tests show the pipeline behaves as designed
on those layouts; they do NOT measure detection accuracy on real documents ("Not yet evaluated").
"""

import hashlib
import io
import shutil

import pymupdf
import pytest
from PIL import Image

from document_processing import (
    IMAGE_EXTRACTED,
    IMAGE_FAILED,
    IMG_OCR_COMPLETED,
    IMG_OCR_FAILED,
    IMG_OCR_NO_TEXT,
    IMG_OCR_NOT_REQUESTED,
    IMG_OCR_SKIPPED_PAGE_SCAN,
    IMG_OCR_UNAVAILABLE,
    MM_PAGE_COMPLETED,
    MM_PAGE_FAILED,
    TABLE_METHOD_PYMUPDF,
    DocumentProcessingError,
    MultimodalProcessor,
    PdfOpenError,
    ProcessingConfig,
    TesseractOcr,
    display_box,
    display_region,
    render_page_png,
)
from tests import pdf_factory as factory
from tests.ocr_stubs import FailingOcr, StubOcr, UnavailableOcr

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")


@pytest.fixture
def write_pdf(tmp_path):
    def _write(data: bytes, name: str = "doc.pdf"):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return _write


def run(path, *, config=None, ocr=None, image_ocr=None):
    with MultimodalProcessor(path, config or ProcessingConfig(), ocr=ocr, image_ocr=image_ocr) as processor:
        return processor.page_count, list(processor.iter_pages())


def grid(table):
    """Cell texts as a list of rows."""
    return [[c.text for c in table.cells[r * table.col_count:(r + 1) * table.col_count]] for r in range(table.row_count)]


# ---------- tables ----------


def test_ruled_table_structure_text_and_location(write_pdf):
    _, pages = run(write_pdf(factory.table_pdf()))
    (page,) = pages
    assert page.status == MM_PAGE_COMPLETED and page.errors == []
    (table,) = page.tables
    assert (table.page_number, table.table_index) == (1, 1)
    assert table.detection_method == TABLE_METHOD_PYMUPDF
    assert (table.row_count, table.col_count) == (4, 4)
    assert len(table.cells) == 16
    assert grid(table) == factory.LAB_TABLE_ROWS  # exact text, including "7.8" and "4.0 - 5.6"
    # location: the table was drawn at x 72..452, y 120..216 (points)
    x0, y0, x1, y1 = table.bbox
    assert (round(x0), round(y0), round(x1), round(y1)) == (72, 120, 452, 216)
    assert (table.page_width, table.page_height, table.page_rotation) == (595.0, 842.0, 0)


def test_cell_boxes_lie_inside_the_table_box(write_pdf):
    (table,) = run(write_pdf(factory.table_pdf()))[1][0].tables
    x0, y0, x1, y1 = table.bbox
    for cell in table.cells:
        cx0, cy0, cx1, cy1 = cell.bbox
        assert x0 - 0.5 <= cx0 < cx1 <= x1 + 0.5 and y0 - 0.5 <= cy0 < cy1 <= y1 + 0.5
    assert [(c.row_index, c.col_index) for c in table.cells][:5] == [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)]


def test_decimals_and_ranges_stay_intact(write_pdf):
    """PyMuPDF's own Table.extract() split "7.8" into "7 8\\n."; our cell text must not."""
    rows = [["Analyte", "Value"], ["Creatinine", "0.92"], ["TSH", "2.35"], ["Range", "0.4 - 4.0"]]
    (table,) = run(write_pdf(factory.table_pdf(rows)))[1][0].tables
    assert grid(table) == rows


def test_borderless_table_is_detected(write_pdf):
    (table,) = run(write_pdf(factory.table_pdf(ruled=False)))[1][0].tables
    assert grid(table) == factory.LAB_TABLE_ROWS


def test_prose_page_has_no_table(write_pdf):
    _, pages = run(write_pdf(factory.text_pdf([["A paragraph of ordinary text.", "Another sentence on a second line."]])))
    assert pages[0].tables == [] and pages[0].errors == []


def test_space_aligned_text_in_a_single_run_is_not_detected(write_pdf):
    """Documented limitation: columns made with runs of spaces inside one text line are not tables."""
    _, pages = run(write_pdf(factory.text_pdf([factory.LAB_REPORT_LINES])))
    assert pages[0].tables == []


@pytest.mark.parametrize("rows", [[["Only", "one", "row"]], [["a"], ["b"], ["c"]]], ids=["one-row", "one-column"])
def test_one_row_or_one_column_grids_are_not_tables(write_pdf, rows):
    assert run(write_pdf(factory.table_pdf(rows)))[1][0].tables == []


def test_grid_without_any_text_is_skipped_and_counted():
    """PyMuPDF normally does not report text-less grids; this guards against decorative boxes if it ever does."""
    from types import SimpleNamespace

    from document_processing.models import PageMultimodalResult
    from document_processing.tables import extract_tables

    cell = (10.0, 10.0, 60.0, 30.0)
    fake_table = SimpleNamespace(
        row_count=2, col_count=2, bbox=(10.0, 10.0, 110.0, 50.0),
        rows=[SimpleNamespace(cells=[cell, cell]), SimpleNamespace(cells=[cell, cell])],
    )
    fake_page = SimpleNamespace(
        rotation=0, rect=pymupdf.Rect(0, 0, 595, 842),
        find_tables=lambda: SimpleNamespace(tables=[fake_table]),
        get_text=lambda kind: [],  # no words anywhere
    )
    result = PageMultimodalResult(page_number=1)
    extract_tables(fake_page, 1, ProcessingConfig(), result, budget=10)
    assert result.tables == [] and result.tables_skipped_empty == 1


def test_tables_are_numbered_in_reading_order_and_images_do_not_interfere(write_pdf):
    _, pages = run(write_pdf(factory.multimodal_pdf()))
    tables = pages[0].tables
    assert [t.table_index for t in tables] == [1, 2]
    assert tables[0].bbox[1] < tables[1].bbox[1]
    assert grid(tables[1])[1] == ["Metformin", "500 mg", "twice daily"]
    assert pages[1].tables == [] and pages[1].images == []


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_page_tables_are_found_and_stored_in_unrotated_space(write_pdf, rotation):
    reference = run(write_pdf(factory.table_pdf(), "a.pdf"))[1][0].tables[0]
    (table,) = run(write_pdf(factory.table_pdf(rotation=rotation), "b.pdf"))[1][0].tables
    assert table.page_rotation == rotation
    assert grid(table) == factory.LAB_TABLE_ROWS
    assert [round(v) for v in table.bbox] == [round(v) for v in reference.bbox]
    assert (table.page_width, table.page_height) == (595.0, 842.0)  # unrotated size


def test_table_cell_limit_is_reported_not_silent(write_pdf):
    config = ProcessingConfig(max_cells_per_table=8)
    (page,) = run(write_pdf(factory.table_pdf()), config=config)[1]
    assert page.tables == [] and page.status == MM_PAGE_FAILED
    assert "MAX_CELLS_PER_TABLE" in page.errors[0]


def test_document_table_limit_counts_skipped_tables(write_pdf):
    _, pages = run(write_pdf(factory.multimodal_pdf()), config=ProcessingConfig(max_tables_per_document=1))
    assert len(pages[0].tables) == 1 and pages[0].tables_skipped_over_limit == 1


def test_scanned_page_yields_no_table(write_pdf):
    """No text layer, so there is nothing to assign to cells (documented limitation)."""
    _, pages = run(write_pdf(factory.scanned_pdf([factory.LAB_REPORT_LINES], fontsize=20)))
    assert pages[0].tables == []


# ---------- geometry ----------


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_box_matches_pymupdf_rotation_matrix(rotation):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    box = (72.0, 120.0, 300.0, 200.0)
    expected = pymupdf.Rect(box) * page.rotation_matrix
    expected.normalize()
    got = display_box(box, 595, 842, rotation)
    assert got == pytest.approx((expected.x0, expected.y0, expected.x1, expected.y1), abs=1e-3)


def test_display_region_is_fractions_of_the_displayed_page():
    assert display_region((59.5, 84.2, 297.5, 421.0), 595, 842, 0) == pytest.approx((0.1, 0.1, 0.4, 0.4), abs=1e-4)
    x, y, w, h = display_region((0, 0, 595, 421), 595, 842, 90)  # top half of the file page becomes the right half
    assert (round(x, 3), round(y, 3), round(w, 3), round(h, 3)) == (0.5, 0.0, 0.5, 1.0)
    assert display_region((-50, -50, 5000, 5000), 595, 842, 0) == (0.0, 0.0, 1.0, 1.0)  # clamped
    assert display_region((0, 0, 1, 1), 0, 0, 0) == (0.0, 0.0, 0.0, 0.0)


def test_rotation_handling_never_modifies_the_file(write_pdf):
    path = write_pdf(factory.table_pdf(rotation=90))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    run(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pymupdf.open(path) as doc:
        assert doc[0].rotation == 90


# ---------- images ----------


def test_image_is_detected_extracted_and_located(write_pdf):
    png = factory.bar_chart_png(240, 140)
    path = write_pdf(factory.image_pdf([(png, (100, 200, 340, 340))]))
    (page,) = run(path)[1]
    (image,) = page.images
    assert (image.page_number, image.image_index) == (1, 1)
    assert (image.width_px, image.height_px) == (240, 140)
    assert image.status == IMAGE_EXTRACTED and image.error_message is None
    assert image.stored_format == "png" and image.original_format == "png"
    assert tuple(round(v) for v in image.bbox) == (100, 200, 340, 340)
    assert not image.is_full_page
    assert image.sha256 == hashlib.sha256(image.data).hexdigest()
    with Image.open(io.BytesIO(image.data)) as decoded:
        assert decoded.size == (240, 140)
    assert image.ocr_status == IMG_OCR_NOT_REQUESTED and image.ocr_text is None


def test_jpeg_is_kept_byte_for_byte(write_pdf):
    jpeg = factory.jpeg_bytes(120, 90)
    (image,) = run(write_pdf(factory.image_pdf([(jpeg, (50, 50, 170, 140))])))[1][0].images
    assert image.stored_format == "jpeg" and image.original_format == "jpeg"
    assert image.data == jpeg


def test_cmyk_jpeg_is_converted_to_png_for_display(write_pdf):
    jpeg = factory.jpeg_bytes(120, 90, mode="CMYK")
    (image,) = run(write_pdf(factory.image_pdf([(jpeg, (50, 50, 170, 140))])))[1][0].images
    assert image.status == IMAGE_EXTRACTED and image.stored_format == "png"
    with Image.open(io.BytesIO(image.data)) as decoded:
        assert decoded.mode in ("RGB", "RGBA") and decoded.size == (120, 90)


def test_tiny_images_are_skipped_and_counted(write_pdf):
    tiny = factory.bar_chart_png(20, 20)
    big = factory.bar_chart_png(100, 80)
    (page,) = run(write_pdf(factory.image_pdf([(tiny, (10, 10, 30, 30)), (big, (100, 100, 200, 180)), (tiny, (50, 10, 70, 30))])))[1]
    assert len(page.images) == 1 and page.images_skipped_small == 2
    assert page.images[0].image_index == 1  # numbering counts stored images only


def test_same_image_placed_twice_gives_two_records_with_their_own_boxes(write_pdf):
    png = factory.bar_chart_png(100, 80)
    (page,) = run(write_pdf(factory.image_pdf([(png, (50, 50, 150, 130)), (png, (50, 300, 150, 380))])))[1]
    assert len(page.images) == 2
    assert page.images[0].sha256 == page.images[1].sha256
    assert page.images[0].bbox != page.images[1].bbox


def test_full_page_image_is_flagged_as_probable_page_scan(write_pdf):
    (page,) = run(write_pdf(factory.scanned_pdf([factory.LAB_REPORT_LINES], fontsize=20)))[1]
    (image,) = page.images
    assert image.is_full_page


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_page_image_boxes_use_unrotated_space(write_pdf, rotation):
    png = factory.bar_chart_png(240, 140)
    rect = (100, 200, 340, 340)
    (image,) = run(write_pdf(factory.image_pdf([(png, rect)], rotation=rotation)))[1][0].images
    assert image.page_rotation == rotation
    assert tuple(round(v) for v in image.bbox) == rect
    assert (image.page_width, image.page_height) == (595.0, 842.0)


def test_image_limit_across_the_document_counts_the_rest(write_pdf):
    png = factory.bar_chart_png(100, 80)
    data = factory.image_pdf([(png, (50, 50, 150, 130)), (png, (50, 300, 150, 380)), (png, (300, 300, 400, 380))])
    (page,) = run(write_pdf(data), config=ProcessingConfig(max_images_per_document=2))[1]
    assert len(page.images) == 2 and page.images_skipped_over_limit == 1


def test_oversized_images_are_recorded_as_failed_with_a_reason(write_pdf):
    png = factory.bar_chart_png(240, 140)
    path = write_pdf(factory.image_pdf([(png, (100, 200, 340, 340))]))
    (too_many_pixels,) = run(path, config=ProcessingConfig(max_image_pixels=1000))[1][0].images
    assert too_many_pixels.status == IMAGE_FAILED and "MAX_IMAGE_PIXELS" in too_many_pixels.error_message
    assert too_many_pixels.data is None and too_many_pixels.bbox is not None
    (too_big,) = run(path, config=ProcessingConfig(max_image_bytes=10))[1][0].images
    assert too_big.status == IMAGE_FAILED and "MAX_IMAGE_BYTES" in too_big.error_message


def test_one_image_failing_does_not_stop_the_others(write_pdf, monkeypatch):
    from document_processing import images as images_module

    real = images_module._extract_bytes
    calls = {"n": 0}

    def flaky(doc, xref):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(doc, xref)

    monkeypatch.setattr(images_module, "_extract_bytes", flaky)
    png1, png2 = factory.bar_chart_png(100, 80), factory.bar_chart_png(120, 90)
    (page,) = run(write_pdf(factory.image_pdf([(png1, (50, 50, 150, 130)), (png2, (50, 300, 170, 390))])))[1]
    first, second = page.images
    assert first.status == IMAGE_FAILED and "RuntimeError" in first.error_message and first.data is None
    assert second.status == IMAGE_EXTRACTED and second.data


def test_a_table_failure_does_not_lose_the_images_and_vice_versa(write_pdf, monkeypatch):
    from document_processing import multimodal as mm

    path = write_pdf(factory.multimodal_pdf())
    monkeypatch.setattr(mm, "extract_tables", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tables broke")))
    page = run(path)[1][0]
    assert page.tables == [] and len(page.images) == 2
    assert page.status == MM_PAGE_FAILED and "Table detection failed" in page.errors[0]
    monkeypatch.undo()

    monkeypatch.setattr(mm, "extract_images", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("images broke")))
    page = run(path)[1][0]
    assert len(page.tables) == 2 and page.images == []
    assert "Image extraction failed" in page.errors[0]


# ---------- optional OCR of text inside images ----------


def test_image_ocr_is_off_by_default(write_pdf):
    ocr = StubOcr()
    (image,) = run(write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))])), ocr=ocr)[1][0].images
    assert ocr.calls == 0 and image.ocr_status == IMG_OCR_NOT_REQUESTED


def test_image_ocr_stores_text_and_confidence_when_requested(write_pdf):
    ocr = StubOcr(text="Series A 7.8 percent", confidence=88.0)
    path = write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))]))
    (image,) = run(path, ocr=ocr, image_ocr=True)[1][0].images
    assert ocr.calls == 1
    assert image.ocr_status == IMG_OCR_COMPLETED and image.ocr_text == "Series A 7.8 percent"
    assert image.ocr_mean_confidence == 88.0 and image.status == IMAGE_EXTRACTED


def test_image_ocr_setting_in_config_enables_it(write_pdf):
    ocr = StubOcr()
    path = write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))]))
    run(path, config=ProcessingConfig(image_ocr=True), ocr=ocr)
    assert ocr.calls == 1


def test_image_ocr_with_too_little_text_is_reported_as_no_text(write_pdf):
    path = write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))]))
    (image,) = run(path, ocr=StubOcr(text="~ .", confidence=12.0), image_ocr=True)[1][0].images
    assert image.ocr_status == IMG_OCR_NO_TEXT and image.ocr_text is None


def test_full_page_scans_are_not_ocred_again_as_images(write_pdf):
    ocr = StubOcr()
    path = write_pdf(factory.scanned_pdf([factory.LAB_REPORT_LINES], fontsize=20))
    (image,) = run(path, ocr=ocr, image_ocr=True)[1][0].images
    assert ocr.calls == 0 and image.ocr_status == IMG_OCR_SKIPPED_PAGE_SCAN


def test_image_ocr_unavailable_is_reported_never_silent(write_pdf):
    path = write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))]))
    (page,) = run(path, ocr=UnavailableOcr("Tesseract OCR was not found. Install it."), image_ocr=True)[1]
    (image,) = page.images
    assert image.ocr_status == IMG_OCR_UNAVAILABLE and image.status == IMAGE_EXTRACTED and image.data
    assert page.status == MM_PAGE_FAILED and "Install it" in page.errors[0]


def test_image_ocr_failure_is_isolated(write_pdf):
    path = write_pdf(factory.image_pdf([(factory.bar_chart_png(), (100, 200, 340, 340))]))
    (image,) = run(path, ocr=FailingOcr(), image_ocr=True)[1][0].images
    assert image.ocr_status == IMG_OCR_FAILED and image.status == IMAGE_EXTRACTED


@needs_tesseract
def test_real_tesseract_reads_printed_text_inside_an_image(write_pdf):
    png = factory.text_image_png(["HEMOGLOBIN 7.8 PERCENT"], fontsize=30, width=520)
    path = write_pdf(factory.image_pdf([(png, (60, 100, 460, 160))]))
    config = ProcessingConfig(image_ocr=True)
    (image,) = run(path, config=config, ocr=TesseractOcr(config))[1][0].images
    assert image.ocr_status == IMG_OCR_COMPLETED
    assert "hemoglobin" in image.ocr_text.lower() and image.ocr_mean_confidence is not None


# ---------- opening / errors ----------


def test_unreadable_encrypted_and_oversized_pdfs_are_rejected_with_codes(write_pdf):
    with pytest.raises(PdfOpenError) as corrupt:
        MultimodalProcessor(write_pdf(b"%PDF-1.4 not really a pdf", "c.pdf")).__enter__()
    assert corrupt.value.code == "invalid_pdf"
    with pytest.raises(PdfOpenError) as encrypted:
        MultimodalProcessor(write_pdf(factory.encrypted_pdf(), "e.pdf")).__enter__()
    assert encrypted.value.code == "encrypted_pdf"
    with pytest.raises(PdfOpenError) as many:
        MultimodalProcessor(write_pdf(factory.blank_pdf(3), "m.pdf"), ProcessingConfig(max_pages=2)).__enter__()
    assert many.value.code == "too_many_pages"


# ---------- page rendering ----------


def test_render_page_png_caps_the_longest_side(write_pdf):
    path = write_pdf(factory.table_pdf())
    png = render_page_png(path, 1, ProcessingConfig(), max_side_px=600)
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG" and max(image.size) == pytest.approx(600, abs=2)
        assert image.height > image.width  # portrait page


def test_render_page_png_applies_page_rotation_like_a_viewer(write_pdf):
    path = write_pdf(factory.table_pdf(rotation=90))
    with Image.open(io.BytesIO(render_page_png(path, 1, ProcessingConfig(), max_side_px=600))) as image:
        assert image.width > image.height  # landscape after rotating the portrait page


def test_render_page_png_rejects_missing_pages_and_bad_files(write_pdf):
    path = write_pdf(factory.table_pdf())
    for number in (0, 2):
        with pytest.raises(DocumentProcessingError) as missing:
            render_page_png(path, number, ProcessingConfig())
        assert missing.value.code == "page_not_found"
    with pytest.raises(PdfOpenError):
        render_page_png(write_pdf(b"junk", "j.pdf"), 1, ProcessingConfig())
