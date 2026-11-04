"""DocumentPage: extracted content of one PDF page.

Traceability chain started here:  document -> page -> extracted text.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.document import Document, utcnow


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # page_id
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    extraction_method: Mapped[str] = mapped_column(String(30), nullable=False)
    # Text exactly as extracted (only NUL characters are removed). Never normalised.
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # non-whitespace chars
    processing_status: Mapped[str] = mapped_column(String(20), nullable=False)
    ocr_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Tesseract's own mean word confidence (0-100). Not an accuracy measure.
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_likely_scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    document: Mapped[Document] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
        Index("ix_document_pages_document_id", "document_id"),
    )
