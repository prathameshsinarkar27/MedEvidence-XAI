"""tables, table cells and embedded images + multimodal status columns on documents.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DOCUMENT_COLUMNS = (
    "multimodal_status", "multimodal_error_code", "multimodal_error", "multimodal_processed_at",
    "multimodal_page_count", "multimodal_pages_processed", "table_count", "image_count", "multimodal_summary",
)


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("multimodal_status", sa.String(length=30), nullable=False, server_default="not_processed"),
    )
    op.add_column("documents", sa.Column("multimodal_error_code", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("multimodal_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("multimodal_processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("multimodal_page_count", sa.Integer(), nullable=True))
    op.add_column(
        "documents", sa.Column("multimodal_pages_processed", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("documents", sa.Column("table_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("image_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("multimodal_summary", sa.JSON(), nullable=True))

    op.create_table(
        "document_tables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("table_index", sa.Integer(), nullable=False),
        sa.Column("detection_method", sa.String(length=40), nullable=False),
        sa.Column("bbox_x0", sa.Float(), nullable=False),
        sa.Column("bbox_y0", sa.Float(), nullable=False),
        sa.Column("bbox_x1", sa.Float(), nullable=False),
        sa.Column("bbox_y1", sa.Float(), nullable=False),
        sa.Column("page_width", sa.Float(), nullable=False),
        sa.Column("page_height", sa.Float(), nullable=False),
        sa.Column("page_rotation", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("col_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", "table_index", name="uq_document_tables_page_index"),
    )
    op.create_index("ix_document_tables_document_id", "document_tables", ["document_id"])

    op.create_table(
        "table_cells",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("table_id", sa.Uuid(), sa.ForeignKey("document_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("col_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("bbox_x0", sa.Float(), nullable=True),
        sa.Column("bbox_y0", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.UniqueConstraint("table_id", "row_index", "col_index", name="uq_table_cells_position"),
    )
    op.create_index("ix_table_cells_table_id", "table_cells", ["table_id"])

    op.create_table(
        "document_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_index", sa.Integer(), nullable=False),
        sa.Column("xref", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("colorspace", sa.String(length=60), nullable=True),
        sa.Column("bits_per_component", sa.Integer(), nullable=True),
        sa.Column("original_format", sa.String(length=20), nullable=True),
        sa.Column("stored_format", sa.String(length=10), nullable=True),
        sa.Column("stored_filename", sa.String(length=100), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("bbox_x0", sa.Float(), nullable=True),
        sa.Column("bbox_y0", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.Column("page_width", sa.Float(), nullable=False),
        sa.Column("page_height", sa.Float(), nullable=False),
        sa.Column("page_rotation", sa.Integer(), nullable=False),
        sa.Column("is_full_page", sa.Boolean(), nullable=False),
        sa.Column("extraction_status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ocr_status", sa.String(length=30), nullable=False),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("ocr_mean_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", "image_index", name="uq_document_images_page_index"),
    )
    op.create_index("ix_document_images_document_id", "document_images", ["document_id"])
    op.execute("UPDATE app_metadata SET value = '4' WHERE key = 'schema_phase'")


def downgrade() -> None:
    op.execute("UPDATE app_metadata SET value = '3' WHERE key = 'schema_phase'")
    op.drop_index("ix_document_images_document_id", table_name="document_images")
    op.drop_table("document_images")
    op.drop_index("ix_table_cells_table_id", table_name="table_cells")
    op.drop_table("table_cells")
    op.drop_index("ix_document_tables_document_id", table_name="document_tables")
    op.drop_table("document_tables")
    for column in reversed(NEW_DOCUMENT_COLUMNS):
        op.drop_column("documents", column)
