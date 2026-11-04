"""Upload validation rules (pure functions, no I/O).

Phase 2 accepts PDF documents only. A file must pass ALL of these checks:
  1. sanitised filename ends in ".pdf"
  2. declared Content-Type is "application/pdf"
  3. content starts with the "%PDF-" signature
  4. content is non-empty and not larger than MAX_UPLOAD_SIZE_MB
(4 is enforced while streaming in `document_storage`.)
The client-supplied filename is only ever used as a display label, never to build a path.
"""

import re
import unicodedata

ALLOWED_EXTENSIONS: tuple[str, ...] = (".pdf",)
ALLOWED_MIME_TYPES: tuple[str, ...] = ("application/pdf",)
PDF_SIGNATURE = b"%PDF-"
MAX_FILENAME_LENGTH = 255
FALLBACK_STEM = "document"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MULTI_UNDERSCORE_SPACE = re.compile(r"[_ ]{2,}")
_ALLOWED_PUNCTUATION = frozenset(" .()-_")


def _replace_unsafe_chars(name: str) -> str:
    """Keep Unicode letters (L*), combining marks (M*) and digits (N*); replace the rest with '_'.

    Marks must be kept explicitly: Python's `\\w` drops them, which would corrupt names in
    scripts such as Devanagari where vowel signs are combining marks.
    """
    return "".join(
        ch if ch in _ALLOWED_PUNCTUATION or unicodedata.category(ch)[0] in "LMN" else "_"
        for ch in name
    )


class UploadValidationError(Exception):
    """A client-correctable upload problem, mapped to an HTTP error by the API layer."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def sanitize_filename(raw: str | None) -> str:
    """Return a safe display filename derived from a client-supplied name.

    Strips any directory part (both / and \\ separators), control characters and
    unusual symbols, removes leading dots, and truncates to MAX_FILENAME_LENGTH
    while preserving the extension.
    """
    if raw is None or not raw.strip():
        raise UploadValidationError(400, "filename_missing", "The uploaded file has no filename.")

    name = unicodedata.normalize("NFC", raw)
    name = _CONTROL_CHARS.sub("", name)
    name = re.split(r"[\\/]", name)[-1]  # basename only: defeats ../ and C:\ paths
    name = _replace_unsafe_chars(name).strip(" ")
    name = _MULTI_UNDERSCORE_SPACE.sub("_", name)
    if name.startswith(".") and name.count(".") == 1 and len(name) > 1:
        name = FALLBACK_STEM + name  # ".pdf" -> "document.pdf" (extension only, no stem)
    name = name.strip(" .")  # no leading/trailing dots or spaces
    if not name:
        raise UploadValidationError(400, "filename_invalid", "The filename contains no usable characters.")

    stem, dot, ext = name.rpartition(".")
    if not dot:  # no extension at all
        stem, ext = name, ""
    stem = stem.strip(" .") or FALLBACK_STEM
    ext_part = f".{ext}" if ext else ""
    stem = stem[: max(1, MAX_FILENAME_LENGTH - len(ext_part))]
    return f"{stem}{ext_part}"


def validate_extension(filename: str) -> str:
    """`filename` must already be sanitised. Returns the lower-case extension."""
    dot = filename.rfind(".")
    ext = filename[dot:].lower() if dot != -1 else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            415, "unsupported_extension", "Only PDF files (.pdf) are accepted."
        )
    return ext


def validate_content_type(content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_MIME_TYPES:
        raise UploadValidationError(
            415,
            "unsupported_content_type",
            "The file's declared type is not application/pdf.",
        )
    return media_type


def validate_pdf_signature(first_bytes: bytes) -> None:
    if not first_bytes.startswith(PDF_SIGNATURE):
        raise UploadValidationError(
            415,
            "invalid_pdf_signature",
            "The file content is not a valid PDF (missing %PDF- header).",
        )
