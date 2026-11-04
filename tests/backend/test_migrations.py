from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

PHASE2_DOCUMENT_COLUMNS = {
    "id", "original_filename", "stored_filename", "file_type", "mime_type",
    "file_size_bytes", "sha256", "storage_path", "upload_status", "uploaded_at",
}
PHASE3_DOCUMENT_COLUMNS = {
    "page_count", "processing_status", "processing_error_code", "processing_error", "processed_at", "pdf_metadata",
}
PAGE_COLUMNS = {
    "id", "document_id", "page_number", "extraction_method", "extracted_text", "char_count",
    "processing_status", "ocr_status", "ocr_mean_confidence", "has_images", "is_likely_scanned",
    "error_message", "created_at",
}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_single_linear_migration_head():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == ["0003"]
    assert [r.revision for r in script.walk_revisions()] == ["0003", "0002", "0001"]


@pytest.mark.integration
def test_upgrade_and_downgrade_roundtrip(set_database_url, test_database_url):
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)

    def phase() -> str:
        with engine.connect() as conn:
            return conn.execute(text("SELECT value FROM app_metadata WHERE key='schema_phase'")).scalar_one()

    def columns(table: str) -> set[str]:
        return {c["name"] for c in inspect(engine).get_columns(table)}

    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        assert {"app_metadata", "documents", "document_pages"} <= set(inspect(engine).get_table_names())
        assert phase() == "3"
        assert columns("documents") == PHASE2_DOCUMENT_COLUMNS | PHASE3_DOCUMENT_COLUMNS
        assert columns("document_pages") == PAGE_COLUMNS
        foreign_keys = inspect(engine).get_foreign_keys("document_pages")
        assert foreign_keys[0]["referred_table"] == "documents"
        assert foreign_keys[0]["options"].get("ondelete", "").upper() == "CASCADE"

        command.downgrade(cfg, "0002")  # Phase 3 can be reverted without losing Phase 2
        assert "document_pages" not in inspect(engine).get_table_names()
        assert columns("documents") == PHASE2_DOCUMENT_COLUMNS
        assert phase() == "2"

        command.downgrade(cfg, "0001")
        assert "documents" not in inspect(engine).get_table_names() and phase() == "1"

        command.downgrade(cfg, "base")
        assert "app_metadata" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")  # leave the test DB migrated
    finally:
        engine.dispose()


@pytest.mark.integration
def test_existing_phase2_rows_survive_upgrade_with_defaults(set_database_url, test_database_url):
    """A Phase 2 database (documents already uploaded) must upgrade cleanly."""
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "0002")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO documents (id, original_filename, stored_filename, file_type, mime_type, "
                    "file_size_bytes, sha256, storage_path, upload_status, uploaded_at) VALUES "
                    "('11111111-1111-1111-1111-111111111111', 'old.pdf', 'old.pdf', 'pdf', 'application/pdf', "
                    "10, 'abc', 'old.pdf', 'uploaded', now())"
                )
            )
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT processing_status, page_count FROM documents")).one()
        assert tuple(row) == ("not_processed", None)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM documents"))
        engine.dispose()
