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


def test_single_migration_head():
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert heads == ["0001"]


@pytest.mark.integration
def test_upgrade_and_downgrade_roundtrip(set_database_url, test_database_url):
    set_database_url(test_database_url)
    cfg = _alembic_config()
    engine = create_engine(test_database_url)
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        assert "app_metadata" in inspect(engine).get_table_names()
        with engine.connect() as conn:
            value = conn.execute(text("SELECT value FROM app_metadata WHERE key='schema_phase'")).scalar_one()
        assert value == "1"

        command.downgrade(cfg, "base")
        assert "app_metadata" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")  # leave the test DB migrated
    finally:
        engine.dispose()
