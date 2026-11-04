"""Document use-cases: create (validate + store + persist) and query."""

import logging
import uuid
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.document import UPLOAD_STATUS_UPLOADED, Document
from app.services import document_storage
from app.services.upload_validation import (
    sanitize_filename,
    validate_content_type,
    validate_extension,
)

logger = logging.getLogger(__name__)


def create_document(
    session: Session,
    settings: Settings,
    *,
    filename: str | None,
    content_type: str | None,
    stream: BinaryIO,
) -> Document:
    # Cheap header checks first, so we never touch the disk for obviously wrong uploads.
    display_name = sanitize_filename(filename)
    validate_extension(display_name)
    mime_type = validate_content_type(content_type)

    document_id = uuid.uuid4()
    stored = document_storage.save_stream(
        stream, settings.upload_dir_path, document_id, settings.max_upload_size_bytes
    )

    document = Document(
        id=document_id,
        original_filename=display_name,
        stored_filename=stored.stored_filename,
        file_type="pdf",
        mime_type=mime_type,
        file_size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        storage_path=stored.storage_path,
        upload_status=UPLOAD_STATUS_UPLOADED,
    )
    try:
        session.add(document)
        session.commit()
    except Exception:
        session.rollback()
        document_storage.remove_stored_file(stored.absolute_path)
        logger.exception("Failed to persist document %s; stored file removed", document_id)
        raise

    # Filenames can contain personal information, so only the id is logged.
    logger.info("Document uploaded id=%s size=%d sha256=%s", document.id, stored.size_bytes, stored.sha256[:12])
    return document


def list_documents(session: Session, limit: int, offset: int) -> tuple[list[Document], int]:
    total = session.scalar(select(func.count()).select_from(Document)) or 0
    items = session.scalars(
        select(Document).order_by(Document.uploaded_at.desc(), Document.id).limit(limit).offset(offset)
    ).all()
    return list(items), total


def get_document(session: Session, document_id: uuid.UUID) -> Document | None:
    return session.get(Document, document_id)
