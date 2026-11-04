"""Detected tables and their cells.

Traceability: document -> page_number -> table -> cell. The box of every table and cell is stored in
"unrotated page space" (PDF points, origin top-left, page /Rotate ignored); see docs/multimodal-processing.md.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.document import utcnow


class DocumentTable(Base):
    __tablename__ = "document_tables"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # table_id
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based within the page
    detection_method: Mapped[str] = mapped_column(String(40), nullable=False)
    bbox_x0: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y0: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y1: Mapped[float] = mapped_column(Float, nullable=False)
    page_width: Mapped[float] = mapped_column(Float, nullable=False)
    page_height: Mapped[float] = mapped_column(Float, nullable=False)
    page_rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    col_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    cells: Mapped[list["TableCell"]] = relationship(
        back_populates="table", cascade="all, delete-orphan", order_by="TableCell.row_index, TableCell.col_index"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", "table_index", name="uq_document_tables_page_index"),
        Index("ix_document_tables_document_id", "document_id"),
    )


class TableCell(Base):
    __tablename__ = "table_cells"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)  # cell_id
    table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_tables.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based
    col_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based
    # NULL = no cell exists at this grid position (e.g. covered by a merged cell); "" = an empty cell.
    # Text is stored as read from the PDF; it is never normalised.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y1: Mapped[float | None] = mapped_column(Float, nullable=True)

    table: Mapped[DocumentTable] = relationship(back_populates="cells")

    __table_args__ = (
        UniqueConstraint("table_id", "row_index", "col_index", name="uq_table_cells_position"),
        Index("ix_table_cells_table_id", "table_id"),
    )
