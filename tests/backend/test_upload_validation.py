import pytest

from app.services.upload_validation import (
    UploadValidationError,
    sanitize_filename,
    validate_content_type,
    validate_extension,
    validate_pdf_signature,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("C:\\Users\\me\\lab report (1).pdf", "lab report (1).pdf"),
        ("/abs/path/file.pdf", "file.pdf"),
        ("  spaced name .pdf ", "spaced name.pdf"),
        (".hidden.pdf", "hidden.pdf"),
        ("a<b>c|d?.pdf", "a_b_c_d_.pdf"),
        ("null\x00byte.pdf", "nullbyte.pdf"),
        ("line\nbreak.pdf", "linebreak.pdf"),
        ("रिपोर्ट.pdf", "रिपोर्ट.pdf"),
        ("noextension", "noextension"),
        (".pdf", "document.pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "///", "\\\\", "...", "\x00\x01"])
def test_sanitize_filename_rejects_unusable(raw):
    with pytest.raises(UploadValidationError) as exc:
        sanitize_filename(raw)
    assert exc.value.status_code == 400


def test_sanitize_filename_truncates_but_keeps_extension():
    name = sanitize_filename("a" * 400 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


def test_sanitized_name_never_contains_path_separators():
    for raw in ["a/b.pdf", "a\\b.pdf", "../x.pdf", "..%2f..%2fx.pdf"]:
        out = sanitize_filename(raw)
        assert "/" not in out and "\\" not in out


@pytest.mark.parametrize("name", ["a.pdf", "A.PDF", "x.y.Pdf"])
def test_validate_extension_accepts_pdf(name):
    assert validate_extension(name) == ".pdf"


@pytest.mark.parametrize("name", ["a.txt", "a.exe", "a.pdf.exe", "a", "a.docx", "pdf", "a.pdfx"])
def test_validate_extension_rejects_others(name):
    with pytest.raises(UploadValidationError) as exc:
        validate_extension(name)
    assert exc.value.status_code == 415
    assert exc.value.code == "unsupported_extension"


@pytest.mark.parametrize("ct", ["application/pdf", "Application/PDF", "application/pdf; charset=binary"])
def test_validate_content_type_accepts_pdf(ct):
    assert validate_content_type(ct) == "application/pdf"


@pytest.mark.parametrize(
    "ct", [None, "", "text/plain", "application/octet-stream", "application/x-msdownload", "image/png"]
)
def test_validate_content_type_rejects_others(ct):
    with pytest.raises(UploadValidationError) as exc:
        validate_content_type(ct)
    assert exc.value.code == "unsupported_content_type"


def test_pdf_signature():
    validate_pdf_signature(b"%PDF-1.7\n...")
    for bad in [b"MZ\x90\x00", b"", b" %PDF-1.4", b"<html>", b"PK\x03\x04"]:
        with pytest.raises(UploadValidationError) as exc:
            validate_pdf_signature(bad)
        assert exc.value.code == "invalid_pdf_signature"
