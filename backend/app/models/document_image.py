"""Embedded images found in a document, with their placement on the page.

The image FILE lives under IMAGE_DIR/<document_id>/<stored_filename>; the database holds only the relative name.
The content of an image is never interpreted (no medical-image analysis).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.document import utcnow


class DocumentImage(Base):
    __tablename__ = "document_images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # image_id
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    image_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based within the page
    xref: Mapped[int] = mapped_column(Integer, nullable=False)  # object number inside the PDF (0 = inline)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    colorspace: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bits_per_component: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # as embedded in the PDF
    stored_format: Mapped[str | None] = mapped_column(String(10), nullable=True)  # png | jpeg
    stored_filename: Mapped[str | None] = mapped_column(String(100), nullable=True)  # relative to IMAGE_DIR/<doc id>
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Placement on the page (unrotated page space, PDF points); NULL if the PDF does not give a usable box.
    bbox_x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_width: Mapped[float] = mapped_column(Float, nullable=False)
    page_height: Mapped[float] = mapped_column(Float, nullable=False)
    page_rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_full_page: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extraction_status: Mapped[str] = mapped_column(String(20), nullable=False)  # extracted | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(30), nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # unverified; never interpreted
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", "image_index", name="uq_document_images_page_index"),
        Index("ix_document_images_document_id", "document_id"),
    )
