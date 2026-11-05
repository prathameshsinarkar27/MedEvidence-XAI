"""Document table: one row per uploaded file (metadata only; the file lives on disk)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UPLOAD_STATUS_UPLOADED = "uploaded"

# Document-level processing status (Phase 3)
PROCESSING_NOT_PROCESSED = "not_processed"
PROCESSING_QUEUED = "queued"
PROCESSING_RUNNING = "processing"
PROCESSING_COMPLETED = "completed"
PROCESSING_COMPLETED_WITH_ERRORS = "completed_with_errors"
PROCESSING_FAILED = "failed"
PROCESSING_IN_PROGRESS = (PROCESSING_QUEUED, PROCESSING_RUNNING)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Sanitised display name derived from the client-supplied name. Never used to build paths.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Server-generated name on disk: "<id>.pdf".
    stored_filename: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "pdf"
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Path relative to UPLOAD_DIR (never an absolute server path).
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    upload_status: Mapped[str] = mapped_column(String(20), nullable=False, default=UPLOAD_STATUS_UPLOADED)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # --- Phase 3: processing ---
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PROCESSING_NOT_PROCESSED, server_default=PROCESSING_NOT_PROCESSED
    )
    processing_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Selected PDF info fields (title, author, producer, dates, ...). May contain personal data.
    pdf_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Phase 4: tables and embedded images (own status, same vocabulary as processing_status) ---
    multimodal_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PROCESSING_NOT_PROCESSED, server_default=PROCESSING_NOT_PROCESSED
    )
    multimodal_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    multimodal_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    multimodal_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    multimodal_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multimodal_pages_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    table_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Counts of things skipped by design (tiny images, text-less grids, limits). See docs/multimodal-processing.md.
    multimodal_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Phase 5: clinical information extraction (own status, same vocabulary) ---
    clinical_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PROCESSING_NOT_PROCESSED, server_default=PROCESSING_NOT_PROCESSED
    )
    clinical_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clinical_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clinical_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clinical_pages_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clinical_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    pages: Mapped[list["DocumentPage"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )

    __table_args__ = (
        Index("ix_documents_uploaded_at", "uploaded_at"),
        Index("ix_documents_sha256", "sha256"),
    )
