"""ORM models. Import every model here so Alembic sees it via Base.metadata."""

from app.models.document import Document
from app.models.document_page import DocumentPage

__all__ = ["Document", "DocumentPage"]
