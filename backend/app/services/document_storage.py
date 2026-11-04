"""Streaming, size-limited, atomic file storage for uploads."""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.services.upload_validation import UploadValidationError, validate_pdf_signature

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class StoredFile:
    stored_filename: str
    storage_path: str  # relative to the upload directory
    absolute_path: Path
    size_bytes: int
    sha256: str


def save_stream(source: BinaryIO, upload_dir: Path, document_id: uuid.UUID, max_bytes: int) -> StoredFile:
    """Validate and persist `source` as `<upload_dir>/<document_id>.pdf`.

    The stream is written to a temporary ".part" file first and atomically renamed once it
    has passed every check, so a rejected or interrupted upload never leaves a partial file
    under a real document name. Raises UploadValidationError for client-correctable problems.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{document_id}.pdf"
    final_path = upload_dir / stored_filename
    temp_path = upload_dir / f".incoming-{uuid.uuid4().hex}.part"

    digest = hashlib.sha256()
    size = 0
    try:
        with open(temp_path, "xb") as out:
            first = True
            while chunk := source.read(CHUNK_SIZE):
                if first:
                    validate_pdf_signature(chunk[:16])
                    first = False
                size += len(chunk)
                if size > max_bytes:
                    raise UploadValidationError(
                        413,
                        "file_too_large",
                        f"The file exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB.",
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise UploadValidationError(400, "file_empty", "The uploaded file is empty.")
        os.replace(temp_path, final_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

    return StoredFile(
        stored_filename=stored_filename,
        storage_path=stored_filename,
        absolute_path=final_path,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def remove_stored_file(path: Path) -> None:
    """Best-effort cleanup used when the database insert fails after the file was stored."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove orphaned upload %s", path.name)
