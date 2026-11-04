"""Library tests. Deterministic: OCR is replaced by stubs except where marked `needs_tesseract`."""

import io
import shutil

import pytest
from PIL import Image

from document_processing import (
    METHOD_NONE,
    METHOD_OCR,
    METHOD_PDFPLUMBER,
    METHOD_PYMUPDF,
    OCR_COMPLETED,
    OCR_FAILED,
    OCR_NOT_NEEDED,
    OCR_UNAVAILABLE,
    PAGE_COMPLETED,
    PAGE_FAILED,
    PAGE_NEEDS_OCR,
    PdfOpenError,
    PdfProcessor,
    ProcessingConfig,
    TesseractOcr,
    check_tesseract,
)
from document_processing.scanned_detection import is_likely_scanned, is_text_sparse
from document_processing.text_extraction import clean_text, count_text_chars
from tests import pdf_factory as factory
from tests.ocr_stubs import FailingOcr, StubOcr, UnavailableOcr

TESSERACT_INSTALLED = shutil.which("tesseract") is not None
needs_tesseract = pytest.mark.skipif(not TESSERACT_INSTALLED, reason="Tesseract is not installed")


def run(path, *, config=None, ocr=None):
    with PdfProcessor(path, config or ProcessingConfig(), ocr=ocr) as processor:
        return processor.page_count, processor.metadata, list(processor.iter_pages())


@pytest.fixture
def write_pdf(tmp_path):
    def _write(data: bytes, name: str = "doc.pdf"):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return _write


# ---------- text layer ----------


def test_text_pdf_is_extracted_per_page_with_page_numbers(write_pdf):
    path = write_pdf(
        factory.text_pdf(
            [["First page content here, with enough characters"], ["Second page content here, also long enough"]]
        )
    )
    count, _, pages = run(path, ocr=StubOcr())
    assert count == 2
    assert [p.page_number for p in pages] == [1, 2]
    assert "First page content" in pages[0].text and "Second page" not in pages[0].text
    assert "Second page content" in pages[1].text
    for p in pages:
        assert p.extraction_method == METHOD_PYMUPDF
        assert p.status == PAGE_COMPLETED
        assert p.ocr_status == OCR_NOT_NEEDED
        assert p.char_count == count_text_chars(p.text) > 0
        assert not p.is_likely_scanned


def test_ocr_is_not_called_for_pages_with_text(write_pdf):
    ocr = StubOcr()
    run(write_pdf(factory.text_pdf([factory.LAB_REPORT_LINES])), ocr=ocr)
    assert ocr.calls == 0


def test_extracted_text_is_preserved_exactly(write_pdf):
    lines = ["Hb 7.8 %   (ref 4.0 - 5.6)", "   indented line with µg/dL and 37 °C"]
    path = write_pdf(factory.text_pdf([lines]))
    import pymupdf

    with pymupdf.open(path) as doc:
        expected = doc[0].get_text("text")
    _, _, pages = run(path, ocr=StubOcr())
    assert pages[0].text == expected  # no normalisation, trimming or reflowing


def test_metadata_is_read_and_empty_values_dropped(write_pdf):
    path = write_pdf(factory.text_pdf([["Some page text for testing"]], title="Synthetic Title"))
    _, metadata, _ = run(path, ocr=StubOcr())
    assert metadata["title"] == "Synthetic Title"
    assert metadata["author"] == "Synthetic Generator"
    assert metadata["format"].startswith("PDF")
    assert "subject" not in metadata and "keywords" not in metadata


def test_clean_text_removes_only_nul_characters():
    assert clean_text("a\x00b\n c ") == "ab\n c "
    assert clean_text(None) == ""


# ---------- sparse / scanned detection ----------


def test_sparse_detection_thresholds():
    assert is_text_sparse("", 25)
    assert is_text_sparse("   \n\t  ab  ", 25)
    assert not is_text_sparse("x" * 25, 25)
    assert is_text_sparse("x" * 24, 25)
    assert count_text_chars(" a b\nc ") == 3


@pytest.mark.parametrize(
    "sparse, images, expected",
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_likely_scanned_rule(sparse, images, expected):
    assert is_likely_scanned(sparse, images) is expected


def test_image_only_page_is_flagged_scanned_and_ocr_is_used(write_pdf):
    ocr = StubOcr("Recognised scanned text, long enough to count", 88.0)
    _, _, pages = run(write_pdf(factory.scanned_pdf([["Hemoglobin A1c 7.8"]])), ocr=ocr)
    page = pages[0]
    assert page.has_images and page.is_likely_scanned
    assert page.extraction_method == METHOD_OCR
    assert page.ocr_status == OCR_COMPLETED
    assert page.ocr_mean_confidence == 88.0
    assert page.text == "Recognised scanned text, long enough to count"
    assert page.status == PAGE_COMPLETED
    assert ocr.calls == 1


def test_mixed_pdf_only_ocrs_the_scanned_page(write_pdf):
    ocr = StubOcr("Scanned page text from the stub OCR engine")
    _, _, pages = run(write_pdf(factory.mixed_pdf(factory.LAB_REPORT_LINES, ["Scanned line"])), ocr=ocr)
    assert [p.extraction_method for p in pages] == [METHOD_PYMUPDF, METHOD_OCR]
    assert ocr.calls == 1


def test_blank_page_yields_no_text_and_method_none(write_pdf):
    _, _, pages = run(write_pdf(factory.blank_pdf()), ocr=StubOcr(text=""))
    page = pages[0]
    assert page.text == "" and page.char_count == 0
    assert page.extraction_method == METHOD_NONE
    assert page.ocr_status == OCR_COMPLETED  # OCR ran and found nothing
    assert page.status == PAGE_COMPLETED
    assert not page.is_likely_scanned  # no embedded image


def test_threshold_is_configurable(write_pdf):
    path = write_pdf(factory.text_pdf([["short text"]]))  # 9 non-space chars
    _, _, with_default = run(path, ocr=StubOcr("ocr output that is clearly longer"))
    assert with_default[0].extraction_method == METHOD_OCR  # 9 < 25 -> sparse -> OCR
    _, _, lowered = run(path, config=ProcessingConfig(min_text_chars=5), ocr=StubOcr())
    assert lowered[0].extraction_method == METHOD_PYMUPDF


def test_ocr_text_replaces_text_only_when_it_is_longer(write_pdf):
    path = write_pdf(factory.text_pdf([["short text"]]))
    _, _, pages = run(path, ocr=StubOcr("ab"))  # OCR found less than the text layer
    assert pages[0].text.startswith("short text")
    assert pages[0].extraction_method == METHOD_PYMUPDF
    assert pages[0].ocr_status == OCR_COMPLETED


def test_pdfplumber_fallback_is_used_when_it_finds_more_text(write_pdf, monkeypatch):
    path = write_pdf(factory.blank_pdf())
    monkeypatch.setattr(
        "document_processing.text_extraction.PdfplumberReader.extract",
        lambda self, i: "Text recovered by the secondary parser, long enough",
    )
    ocr = StubOcr()
    _, _, pages = run(path, ocr=ocr)
    assert pages[0].extraction_method == METHOD_PDFPLUMBER
    assert pages[0].ocr_status == OCR_NOT_NEEDED
    assert ocr.calls == 0


# ---------- OCR problems are reported, never silent ----------


def test_ocr_unavailable_marks_page_needs_ocr_with_setup_message(write_pdf):
    message = "Tesseract OCR was not found. Install it."
    _, _, pages = run(write_pdf(factory.scanned_pdf([["x"]])), ocr=UnavailableOcr(message))
    page = pages[0]
    assert page.status == PAGE_NEEDS_OCR
    assert page.ocr_status == OCR_UNAVAILABLE
    assert page.error_message == message
    assert page.extraction_method == METHOD_NONE and page.text == ""


def test_ocr_failure_marks_only_that_page_failed(write_pdf):
    _, _, pages = run(write_pdf(factory.mixed_pdf(factory.LAB_REPORT_LINES, ["x"])), ocr=FailingOcr())
    assert pages[0].status == PAGE_COMPLETED
    assert pages[1].status == PAGE_FAILED and pages[1].ocr_status == OCR_FAILED
    assert "OCR" in pages[1].error_message


def test_one_broken_page_does_not_stop_the_rest(write_pdf, monkeypatch):
    path = write_pdf(factory.text_pdf([["page one has text"], ["page two has text"], ["page three has text"]]))
    original = PdfProcessor._process_page

    def flaky(self, index):
        if index == 1:
            raise ValueError("boom")
        return original(self, index)

    monkeypatch.setattr(PdfProcessor, "_process_page", flaky)
    _, _, pages = run(path, ocr=StubOcr())
    assert [p.status for p in pages] == [PAGE_COMPLETED, PAGE_FAILED, PAGE_COMPLETED]
    assert "ValueError" in pages[1].error_message and "boom" not in pages[1].error_message


# ---------- documents that cannot be processed ----------


def test_corrupt_pdf_raises_invalid_pdf(write_pdf):
    path = write_pdf(b"%PDF-1.4\nthis is not really a pdf\n%%EOF")
    with pytest.raises(PdfOpenError) as exc:
        PdfProcessor(path).__enter__()
    assert exc.value.code == "invalid_pdf"


def test_encrypted_pdf_is_rejected_with_clear_code(write_pdf):
    with pytest.raises(PdfOpenError) as exc:
        PdfProcessor(write_pdf(factory.encrypted_pdf())).__enter__()
    assert exc.value.code == "encrypted_pdf"
    assert "password" in exc.value.message.lower()


def test_page_limit_enforced(write_pdf):
    path = write_pdf(factory.blank_pdf(3))
    with pytest.raises(PdfOpenError) as exc:
        PdfProcessor(path, ProcessingConfig(max_pages=2)).__enter__()
    assert exc.value.code == "too_many_pages"
    assert PdfProcessor(path, ProcessingConfig(max_pages=3), ocr=StubOcr()).__enter__().page_count == 3


def test_missing_file_raises_invalid_pdf(tmp_path):
    with pytest.raises(PdfOpenError):
        PdfProcessor(tmp_path / "nope.pdf").__enter__()


def test_oversized_page_is_downscaled_for_ocr(write_pdf):
    path = write_pdf(factory.large_page_pdf(10000, 6000))
    with PdfProcessor(path, ProcessingConfig(ocr_dpi=300, max_ocr_image_side_px=1500), ocr=StubOcr()) as processor:
        png = processor._render_png(processor._doc[0])
    with Image.open(io.BytesIO(png)) as image:
        assert max(image.size) <= 1510


# ---------- real Tesseract ----------


def test_check_tesseract_reports_missing_binary_with_setup_help():
    status = check_tesseract(ProcessingConfig(tesseract_cmd="/definitely/not/here/tesseract"))
    assert status.available is False
    assert "Tesseract OCR was not found" in status.message
    assert "TESSERACT_CMD" in status.message and "apt install" in status.message


def test_real_ocr_object_raises_unavailable_error_when_binary_missing(write_pdf):
    ocr = TesseractOcr(ProcessingConfig(tesseract_cmd="/definitely/not/here/tesseract"))
    _, _, pages = run(write_pdf(factory.scanned_pdf([["Hemoglobin A1c 7.8"]])), ocr=ocr)
    assert pages[0].status == PAGE_NEEDS_OCR
    assert pages[0].ocr_status == OCR_UNAVAILABLE
    assert "Install" in pages[0].error_message


@needs_tesseract
def test_check_tesseract_reports_version_and_languages():
    status = check_tesseract(ProcessingConfig())
    assert status.available and status.version
    assert "eng" in status.installed_languages


@needs_tesseract
def test_missing_language_data_is_reported():
    status = check_tesseract(ProcessingConfig(ocr_languages="eng+zzz"))
    assert status.available is False
    assert status.missing_languages == ["zzz"]
    assert "zzz" in status.message


@needs_tesseract
def test_real_tesseract_reads_a_synthetic_scanned_page(write_pdf):
    """Smoke test on one clean synthetic image: checks the wiring works, NOT OCR accuracy."""
    path = write_pdf(factory.scanned_pdf([["Hemoglobin A1c 7.8 percent", "Fasting glucose 110 mg/dL"]]))
    _, _, pages = run(path)
    page = pages[0]
    assert page.extraction_method == METHOD_OCR and page.ocr_status == OCR_COMPLETED
    assert page.is_likely_scanned
    assert "hemoglobin" in page.text.lower()
    assert page.ocr_mean_confidence is not None and page.ocr_mean_confidence > 0
