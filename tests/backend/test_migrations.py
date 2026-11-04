from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_single_linear_migration_head():
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == ["0002"]
    assert [r.revision for r in script.walk_revisions()] == ["0002", "0001"]


@pytest.mark.integration
def test_upgrade_and_downgrade_roundtrip(set_database_url, test_database_url):
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)

    def phase() -> str:
        with engine.connect() as conn:
            return conn.execute(text("SELECT value FROM app_metadata WHERE key='schema_phase'")).scalar_one()

    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        tables = inspect(engine).get_table_names()
        assert {"app_metadata", "documents"} <= set(tables)
        assert phase() == "2"

        columns = {c["name"] for c in inspect(engine).get_columns("documents")}
        assert columns == {
            "id", "original_filename", "stored_filename", "file_type", "mime_type",
            "file_size_bytes", "sha256", "storage_path", "upload_status", "uploaded_at",
        }

        command.downgrade(cfg, "0001")  # Phase 2 can be reverted without losing Phase 1
        tables = inspect(engine).get_table_names()
        assert "documents" not in tables and "app_metadata" in tables
        assert phase() == "1"

        command.downgrade(cfg, "base")
        assert "app_metadata" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")  # leave the test DB migrated
    finally:
        engine.dispose()
