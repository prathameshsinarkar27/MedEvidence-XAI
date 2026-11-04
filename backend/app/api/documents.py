"""Document upload and management endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.document import DocumentList, DocumentOut, UploadPolicy
from app.services import documents as document_service
from app.services.upload_validation import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/upload-policy", response_model=UploadPolicy, summary="Accepted file types and size limit")
def upload_policy() -> UploadPolicy:
    return UploadPolicy(
        accepted_file_type="PDF",
        allowed_extensions=list(ALLOWED_EXTENSIONS),
        allowed_mime_types=list(ALLOWED_MIME_TYPES),
        max_upload_size_bytes=get_settings().max_upload_size_bytes,
    )


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF document",
)
def upload_document(
    file: UploadFile = File(..., description="A PDF file"),
    session: Session = Depends(get_session),
) -> DocumentOut:
    document = document_service.create_document(
        session,
        get_settings(),
        filename=file.filename,
        content_type=file.content_type,
        stream=file.file,
    )
    return DocumentOut.model_validate(document)


@router.get("", response_model=DocumentList, summary="List documents (newest first)")
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> DocumentList:
    items, total = document_service.list_documents(session, limit, offset)
    return DocumentList(
        items=[DocumentOut.model_validate(d) for d in items], total=total, limit=limit, offset=offset
    )


@router.get("/{document_id}", response_model=DocumentOut, summary="Document metadata")
def get_document(document_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentOut:
    document = document_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "document_not_found", "message": "Document not found."},
        )
    return DocumentOut.model_validate(document)
