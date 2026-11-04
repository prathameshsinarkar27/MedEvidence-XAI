"""ORM models. Import every model here so Alembic sees it via Base.metadata."""

from app.models.document import Document
from app.models.document_image import DocumentImage
from app.models.document_page import DocumentPage
from app.models.document_table import DocumentTable, TableCell

__all__ = ["Document", "DocumentImage", "DocumentPage", "DocumentTable", "TableCell"]
