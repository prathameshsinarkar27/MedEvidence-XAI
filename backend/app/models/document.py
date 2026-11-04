"""Document table: one row per uploaded file (metadata only; the file lives on disk)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UPLOAD_STATUS_UPLOADED = "uploaded"


def _utcnow() -> datetime:
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
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_documents_uploaded_at", "uploaded_at"),
        Index("ix_documents_sha256", "sha256"),
    )
