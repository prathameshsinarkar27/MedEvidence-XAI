"""Response models for clinical information extraction (Phase 5)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.multimodal import BoxOut, RegionOut


class ClinicalAccepted(BaseModel):
    document_id: uuid.UUID
    clinical_status: str


class ClinicalStatusOut(BaseModel):
    document_id: uuid.UUID
    clinical_status: str  # not_processed | queued | processing | completed | completed_with_errors | failed
    page_count: int | None
    pages_processed: int
    evidence_count: int | None
    by_entity_type: dict[str, int]
    by_modality: dict[str, int]
    by_assertion: dict[str, int]
    summary: dict | None  # what was used / skipped by design
    extractor_version: str
    error_code: str | None
    error_message: str | None
    processed_at: datetime | None
    note: str  # evaluation / confidence caveat, always present


class EvidenceOut(BaseModel):
    evidence_id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    modality: str
    entity_type: str
    entity_name: str
    assertion: str
    mention_text: str
    source_text: str
    source_field: str
    char_start: int | None
    char_end: int | None
    source_start: int | None
    source_end: int | None
    value_text: str | None
    value_numeric: float | None
    value_comparator: str | None
    unit_text: str | None
    unit_normalized: str | None
    reference_text: str | None
    reference_low: float | None
    reference_high: float | None
    abnormal_flag: str | None
    flag_source: str | None
    date_text: str | None
    date_iso: str | None
    attributes: dict
    table_id: uuid.UUID | None
    table_row_index: int | None
    cell_positions: list[list[int]]
    image_id: uuid.UUID | None
    bbox: BoxOut | None
    region: RegionOut | None
    page_width: float | None
    page_height: float | None
    page_rotation: int | None
    extraction_method: str
    extractor_version: str
    extraction_confidence: float
    confidence_factors: dict
    ocr_confidence: float | None


class EvidenceList(BaseModel):
    document_id: uuid.UUID
    total: int
    limit: int
    offset: int
    items: list[EvidenceOut]
