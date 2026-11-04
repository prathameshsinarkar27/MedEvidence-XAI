"""Phase 2: documents table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=100), nullable=False, unique=True),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("upload_status", sa.String(length=20), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_uploaded_at", "documents", ["uploaded_at"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.execute("UPDATE app_metadata SET value = '2' WHERE key = 'schema_phase'")


def downgrade() -> None:
    op.execute("UPDATE app_metadata SET value = '1' WHERE key = 'schema_phase'")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_uploaded_at", table_name="documents")
    op.drop_table("documents")
