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
