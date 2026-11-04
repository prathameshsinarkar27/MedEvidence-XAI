"""ORM models. Import every model here so Alembic sees it via Base.metadata."""

from app.models.document import Document

__all__ = ["Document"]
