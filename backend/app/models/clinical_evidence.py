"""ClinicalEvidence: one extracted clinical fact with its full source trail (Phase 5).

Traceability chain:  document -> page -> (table -> row/cells | image | text span) -> evidence.
The mention and its sentence/row are stored verbatim (`mention_text`, `source_text`); normalised fields sit
beside the originals and never replace them. Bounding boxes use "unrotated page space" like Phase 4.
Deliberately absent: any verification / conflict status (Phases 8-9).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.document import utcnow


class ClinicalEvidence(Base):
    __tablename__ = "clinical_evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # evidence_id
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # stable order within the document

    modality: Mapped[str] = mapped_column(String(20), nullable=False)  # text | ocr | table | image_ocr
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # lab_result | vital_sign | medication | condition | symptom | date
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)  # canonical name
    assertion: Mapped[str] = mapped_column(String(20), nullable=False, default="affirmed")

    # --- exact source ---
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_field: Mapped[str] = mapped_column(String(20), nullable=False)  # page_text | image_ocr_text | table_row
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # mention span within the source field
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # source_text span within the field
    source_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- value: original text beside the normalised form ---
    value_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_comparator: Mapped[str | None] = mapped_column(String(2), nullable=True)
    unit_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    abnormal_flag: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high | low | normal (only from printed evidence)
    flag_source: Mapped[str | None] = mapped_column(String(30), nullable=True)  # printed_flag | printed_reference_range
    date_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_iso: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD, NULL when ambiguous
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # dose frequency route, systolic, role, ...

    # --- table / image provenance (SET NULL if the table or image is later regenerated) ---
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_tables.id", ondelete="SET NULL"), nullable=True)
    table_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-based
    cell_positions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [[row, col], ...] the evidence was read from
    image_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_images.id", ondelete="SET NULL"), nullable=True)

    # --- location on the page (unrotated page space, PDF points); NULL when it cannot be located ---
    bbox_x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_rotation: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- how it was extracted ---
    extraction_method: Mapped[str] = mapped_column(String(60), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # Heuristic rule score, NOT a probability and not calibrated. See docs/ml-methodology.md.
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # Tesseract's own 0-100 mean, if OCR text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_clinical_evidence_document_page", "document_id", "page_number"),
        Index("ix_clinical_evidence_document_type", "document_id", "entity_type"),
        Index("ix_clinical_evidence_entity_name", "entity_name"),  # Phase 6: retrieval by entity across documents
    )
