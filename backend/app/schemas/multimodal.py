"""Response models for tables, images and multimodal processing status (Phase 4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class BoxOut(BaseModel):
    """A rectangle in PDF points in UNROTATED page space (origin top-left, page /Rotate ignored)."""

    x0: float
    y0: float
    x1: float
    y1: float


class RegionOut(BaseModel):
    """The same rectangle as fractions (0-1) of the page AS DISPLAYED (rotation applied): ready for an overlay."""

    x: float
    y: float
    width: float
    height: float


class MultimodalAccepted(BaseModel):
    document_id: uuid.UUID
    multimodal_status: str


class MultimodalStatusOut(BaseModel):
    document_id: uuid.UUID
    multimodal_status: str  # not_processed | queued | processing | completed | completed_with_errors | failed
    page_count: int | None
    pages_processed: int
    table_count: int | None
    image_count: int | None
    images_by_status: dict[str, int]  # extracted | failed
    images_by_ocr_status: dict[str, int]
    pages_with_tables: int
    pages_with_images: int
    summary: dict[str, int | bool] | None  # things skipped by design (tiny images, limits, ...)
    error_code: str | None
    error_message: str | None
    processed_at: datetime | None


class TableSummary(BaseModel):
    id: uuid.UUID  # table_id
    document_id: uuid.UUID
    page_number: int
    table_index: int
    detection_method: str
    row_count: int
    col_count: int
    bbox: BoxOut
    region: RegionOut
    page_width: float
    page_height: float
    page_rotation: int


class CellOut(BaseModel):
    id: uuid.UUID  # cell_id
    row_index: int
    col_index: int
    text: str | None  # null = no cell at this grid position (e.g. merged); "" = empty cell
    bbox: BoxOut | None


class TableDetail(TableSummary):
    cells: list[CellOut]
    rows: list[list[str | None]]  # the same texts as a row-major grid, for display


class TableList(BaseModel):
    document_id: uuid.UUID
    items: list[TableSummary]


class ImageSummary(BaseModel):
    id: uuid.UUID  # image_id
    document_id: uuid.UUID
    page_number: int
    image_index: int
    width_px: int
    height_px: int
    colorspace: str | None
    bits_per_component: int | None
    original_format: str | None
    stored_format: str | None
    file_size_bytes: int | None
    sha256: str | None
    bbox: BoxOut | None
    region: RegionOut | None
    page_width: float
    page_height: float
    page_rotation: int
    is_full_page: bool
    extraction_status: str
    error_message: str | None
    ocr_status: str
    ocr_char_count: int
    ocr_mean_confidence: float | None
    has_file: bool


class ImageDetail(ImageSummary):
    ocr_text: str | None  # unverified text printed inside the image; the image itself is never interpreted


class ImageList(BaseModel):
    document_id: uuid.UUID
    items: list[ImageSummary]
