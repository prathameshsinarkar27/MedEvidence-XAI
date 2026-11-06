"""evidence_embeddings table + evidence index status columns on documents.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DOCUMENT_COLUMNS = ("index_status", "index_error_code", "index_error", "indexed_at", "indexed_count", "index_model")


def upgrade() -> None:
    op.add_column("documents", sa.Column("index_status", sa.String(length=30), nullable=False, server_default="not_processed"))
    op.add_column("documents", sa.Column("index_error_code", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("index_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("indexed_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("index_model", sa.String(length=200), nullable=True))

    op.create_table(
        "evidence_embeddings",
        sa.Column("evidence_id", sa.Uuid(), sa.ForeignKey("clinical_evidence.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("backend", sa.String(length=30), nullable=False),
        sa.Column("text_version", sa.String(length=10), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_embeddings_document", "evidence_embeddings", ["document_id"])
    op.create_index("ix_evidence_embeddings_model", "evidence_embeddings", ["model_name"])
    # Browsing evidence across documents (Phase 6 retrieval) filters on these.
    op.create_index("ix_clinical_evidence_entity_name", "clinical_evidence", ["entity_name"])
    op.execute("UPDATE app_metadata SET value = '6' WHERE key = 'schema_phase'")


def downgrade() -> None:
    op.execute("UPDATE app_metadata SET value = '5' WHERE key = 'schema_phase'")
    op.drop_index("ix_clinical_evidence_entity_name", table_name="clinical_evidence")
    op.drop_index("ix_evidence_embeddings_model", table_name="evidence_embeddings")
    op.drop_index("ix_evidence_embeddings_document", table_name="evidence_embeddings")
    op.drop_table("evidence_embeddings")
    for column in reversed(NEW_DOCUMENT_COLUMNS):
        op.drop_column("documents", column)
