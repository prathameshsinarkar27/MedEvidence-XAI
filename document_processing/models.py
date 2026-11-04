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

    # --- Phase 4: tables and embedded images ---
    # Embedded images whose shorter side is below this many pixels (icons, rules, spacers) are not stored.
    min_image_side_px: int = 32
    max_images_per_document: int = 200
    max_tables_per_document: int = 500
    max_image_bytes: int = 10 * 1024 * 1024  # an image whose stored bytes exceed this is recorded as failed
    max_image_pixels: int = 50_000_000  # decoded-size guard against decompression bombs
    max_cells_per_table: int = 5000  # larger detected grids are reported as errors, not stored
    # An image covering at least this share of the page area is flagged as a probable full-page scan.
    full_page_fraction: float = 0.9
    # Optional OCR of text inside extracted images (off by default; needs Tesseract).
    image_ocr: bool = False
    # OCR output with fewer non-whitespace characters than this is treated as "no text found" (heuristic).
    image_ocr_min_chars: int = 10
    preview_max_side_px: int = 1400


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


# ===================== Phase 4: multimodal (tables and images) =====================

# --- table detection ---
TABLE_METHOD_PYMUPDF = "pymupdf_find_tables"

# --- image extraction status ---
IMAGE_EXTRACTED = "extracted"
IMAGE_FAILED = "failed"

# --- image OCR status ---
IMG_OCR_NOT_REQUESTED = "not_requested"
IMG_OCR_COMPLETED = "completed"  # text found and stored
IMG_OCR_NO_TEXT = "no_text"  # OCR ran; nothing above the minimum length was found
IMG_OCR_SKIPPED_PAGE_SCAN = "skipped_page_scan"  # full-page image; the page text pipeline already covers it
IMG_OCR_UNAVAILABLE = "unavailable"  # OCR requested but Tesseract is missing/misconfigured
IMG_OCR_FAILED = "failed"

# --- per-page multimodal status ---
MM_PAGE_COMPLETED = "completed"
MM_PAGE_FAILED = "failed"  # something on this page could not be processed; see errors


# A box is (x0, y0, x1, y1) in PDF points, origin at the top-left of the page as stored in the file with
# its /Rotate ignored ("unrotated page space"). See docs/multimodal-processing.md.
BBox = tuple[float, float, float, float]


@dataclass
class TableCellResult:
    row_index: int  # 0-based
    col_index: int  # 0-based
    text: str | None  # None = no cell exists here (e.g. covered by a merged cell); "" = empty cell
    bbox: BBox | None


@dataclass
class TableResult:
    page_number: int  # 1-based
    table_index: int  # 1-based, in reading order on the page
    detection_method: str
    bbox: BBox
    page_width: float  # unrotated page size in points
    page_height: float
    page_rotation: int  # 0, 90, 180 or 270
    row_count: int
    col_count: int
    cells: list[TableCellResult]


@dataclass
class ImageResult:
    page_number: int
    image_index: int  # 1-based, in order of appearance on the page
    xref: int
    width_px: int
    height_px: int
    colorspace: str | None
    bits_per_component: int | None
    original_format: str | None  # as embedded in the PDF (jpeg, png, jpx, ...)
    stored_format: str | None  # "png" or "jpeg": what `data` holds
    data: bytes | None
    sha256: str | None
    bbox: BBox | None  # None when the PDF does not say where the image is placed
    page_width: float
    page_height: float
    page_rotation: int
    is_full_page: bool
    status: str  # IMAGE_EXTRACTED | IMAGE_FAILED
    error_message: str | None
    ocr_status: str
    ocr_text: str | None
    ocr_mean_confidence: float | None


@dataclass
class PageMultimodalResult:
    page_number: int
    tables: list[TableResult] = field(default_factory=list)
    images: list[ImageResult] = field(default_factory=list)
    tables_skipped_empty: int = 0  # detected grids with no text at all (decorative boxes, graphics)
    images_skipped_small: int = 0
    images_skipped_over_limit: int = 0
    tables_skipped_over_limit: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return MM_PAGE_FAILED if self.errors else MM_PAGE_COMPLETED
