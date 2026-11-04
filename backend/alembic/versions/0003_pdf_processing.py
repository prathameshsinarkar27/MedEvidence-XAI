"""processing columns on documents + document_pages table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DOCUMENT_COLUMNS = (
    "page_count", "processing_status", "processing_error_code", "processing_error", "processed_at", "pdf_metadata",
)


def upgrade() -> None:
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("processing_status", sa.String(length=30), nullable=False, server_default="not_processed"),
    )
    op.add_column("documents", sa.Column("processing_error_code", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("processing_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("pdf_metadata", sa.JSON(), nullable=True))

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.String(length=30), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("ocr_status", sa.String(length=20), nullable=False),
        sa.Column("ocr_mean_confidence", sa.Float(), nullable=True),
        sa.Column("has_images", sa.Boolean(), nullable=False),
        sa.Column("is_likely_scanned", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.execute("UPDATE app_metadata SET value = '3' WHERE key = 'schema_phase'")


def downgrade() -> None:
    op.execute("UPDATE app_metadata SET value = '2' WHERE key = 'schema_phase'")
    op.drop_index("ix_document_pages_document_id", table_name="document_pages")
    op.drop_table("document_pages")
    for column in reversed(NEW_DOCUMENT_COLUMNS):
        op.drop_column("documents", column)
