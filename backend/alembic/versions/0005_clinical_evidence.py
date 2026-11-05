"""Phase 5: clinical_evidence table + clinical extraction status columns on documents.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DOCUMENT_COLUMNS = (
    "clinical_status", "clinical_error_code", "clinical_error", "clinical_processed_at", "clinical_page_count",
    "clinical_pages_processed", "evidence_count", "clinical_summary",
)


def upgrade() -> None:
    op.add_column("documents", sa.Column("clinical_status", sa.String(length=30), nullable=False, server_default="not_processed"))
    op.add_column("documents", sa.Column("clinical_error_code", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("clinical_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("clinical_processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("clinical_page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("clinical_pages_processed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("evidence_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("clinical_summary", sa.JSON(), nullable=True))

    op.create_table(
        "clinical_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("modality", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_name", sa.String(length=200), nullable=False),
        sa.Column("assertion", sa.String(length=20), nullable=False),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_field", sa.String(length=20), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column("value_text", sa.String(length=100), nullable=True),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_comparator", sa.String(length=2), nullable=True),
        sa.Column("unit_text", sa.String(length=50), nullable=True),
        sa.Column("unit_normalized", sa.String(length=30), nullable=True),
        sa.Column("reference_text", sa.String(length=100), nullable=True),
        sa.Column("reference_low", sa.Float(), nullable=True),
        sa.Column("reference_high", sa.Float(), nullable=True),
        sa.Column("abnormal_flag", sa.String(length=10), nullable=True),
        sa.Column("flag_source", sa.String(length=30), nullable=True),
        sa.Column("date_text", sa.String(length=50), nullable=True),
        sa.Column("date_iso", sa.String(length=10), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("table_id", sa.Uuid(), sa.ForeignKey("document_tables.id", ondelete="SET NULL"), nullable=True),
        sa.Column("table_row_index", sa.Integer(), nullable=True),
        sa.Column("cell_positions", sa.JSON(), nullable=True),
        sa.Column("image_id", sa.Uuid(), sa.ForeignKey("document_images.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bbox_x0", sa.Float(), nullable=True),
        sa.Column("bbox_y0", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.Column("page_width", sa.Float(), nullable=True),
        sa.Column("page_height", sa.Float(), nullable=True),
        sa.Column("page_rotation", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=60), nullable=False),
        sa.Column("extractor_version", sa.String(length=20), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("confidence_factors", sa.JSON(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clinical_evidence_document_page", "clinical_evidence", ["document_id", "page_number"])
    op.create_index("ix_clinical_evidence_document_type", "clinical_evidence", ["document_id", "entity_type"])
    op.execute("UPDATE app_metadata SET value = '5' WHERE key = 'schema_phase'")


def downgrade() -> None:
    op.execute("UPDATE app_metadata SET value = '4' WHERE key = 'schema_phase'")
    op.drop_index("ix_clinical_evidence_document_type", table_name="clinical_evidence")
    op.drop_index("ix_clinical_evidence_document_page", table_name="clinical_evidence")
    op.drop_table("clinical_evidence")
    for column in reversed(NEW_DOCUMENT_COLUMNS):
        op.drop_column("documents", column)
