import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    file_type: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    storage_path: str  # relative to the configured upload directory
    upload_status: str
    uploaded_at: datetime
    # Phase 3
    page_count: int | None = None
    processing_status: str = "not_processed"
    processing_error_code: str | None = None
    processing_error: str | None = None
    processed_at: datetime | None = None
    pdf_metadata: dict[str, str] | None = None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class UploadPolicy(BaseModel):
    accepted_file_type: str
    allowed_extensions: list[str]
    allowed_mime_types: list[str]
    max_upload_size_bytes: int
