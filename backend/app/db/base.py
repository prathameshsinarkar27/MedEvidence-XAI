"""Declarative base for ORM models.

Phase 1 defines no ORM models; Phase 2 introduces the first (Document).
Alembic autogeneration targets `Base.metadata`.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
