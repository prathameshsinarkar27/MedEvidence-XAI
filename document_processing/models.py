"""Plain data containers shared by the library and the backend."""

from dataclasses import dataclass, field

# --- extraction methods (what produced the stored text) ---
METHOD_PYMUPDF = "pymupdf"
METHOD_PDFPLUMBER = "pdfplumber"
METHOD_OCR = "ocr_tesseract"
METHOD_NONE = "none"  # nothing could be extracted and nothing was attempted/successful

# --- per-page OCR status ---
OCR_NOT_NEEDED = "not_needed"
OCR_COMPLETED = "completed"
OCR_UNAVAILABLE = "unavailable"  # OCR was needed but Tesseract is missing/misconfigured
OCR_FAILED = "failed"  # OCR was attempted for this page and errored

# --- per-page processing status ---
PAGE_COMPLETED = "completed"
PAGE_NEEDS_OCR = "needs_ocr"  # page has (almost) no text and OCR could not be run
PAGE_FAILED = "failed"


@dataclass(frozen=True)
class ProcessingConfig:
    # A page whose extracted text has fewer non-whitespace characters than this is treated as
    # "sparse" (little or no text layer). A heuristic; not evaluated.
    min_text_chars: int = 25
    ocr_languages: str = "eng"  # Tesseract language codes joined with "+"
    ocr_dpi: int = 200
    ocr_timeout_seconds: int = 60
    max_pages: int = 300
    max_ocr_image_side_px: int = 4000
    tesseract_cmd: str | None = None


@dataclass
class TesseractStatus:
    available: bool
    version: str | None = None
    requested_languages: list[str] = field(default_factory=list)
    installed_languages: list[str] = field(default_factory=list)
    missing_languages: list[str] = field(default_factory=list)
    message: str | None = None  # setup instructions when not available


@dataclass
class OcrResult:
    text: str
    mean_confidence: float | None  # Tesseract's own mean word confidence (0-100); NOT an accuracy measure


@dataclass
class PageResult:
    page_number: int  # 1-based
    text: str  # as extracted, apart from removal of NUL characters
    extraction_method: str
    char_count: int  # non-whitespace characters
    has_images: bool
    is_likely_scanned: bool
    ocr_status: str
    ocr_mean_confidence: float | None
    status: str
    error_message: str | None = None
