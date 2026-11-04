import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register models on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine, get_session, get_session_factory


def _reset_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def set_database_url(monkeypatch):
    """Point the app at a given DATABASE_URL ('' means not configured)."""

    def _set(url: str) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("LOG_DIR", "")  # no log files during tests
        _reset_caches()

    yield _set
    _reset_caches()


@pytest.fixture
def client(set_database_url):
    set_database_url("")  # default: DB not configured; tests override as needed
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def test_database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


@pytest.fixture(
    params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)],
)
def api(request, tmp_path, monkeypatch, set_database_url):
    """TestClient wired to a database and an isolated upload directory (1 MB size limit).

    Runs against in-memory SQLite always, and against real PostgreSQL (migrated with Alembic)
    when TEST_DATABASE_URL is set.
    """
    upload_dir = tmp_path / "uploads"
    image_dir = tmp_path / "images"
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("IMAGE_DIR", str(image_dir))
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")

    if request.param == "sqlite":
        set_database_url("")
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        from app.main import create_app

        app = create_app()

        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        def _session():
            with factory() as session:
                yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_session_factory] = lambda: factory
    else:
        url = request.getfixturevalue("test_database_url")
        set_database_url(url)
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")
        with create_engine(url).begin() as conn:
            conn.execute(text("DELETE FROM table_cells"))
            conn.execute(text("DELETE FROM documents"))
        from app.main import create_app

        app = create_app()
        engine = create_engine(url)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.upload_dir = upload_dir  # type: ignore[attr-defined]
        test_client.image_dir = image_dir  # type: ignore[attr-defined]
        test_client.session_factory = factory  # type: ignore[attr-defined]
        yield test_client
    engine.dispose()


@pytest.fixture
def configure(monkeypatch):
    """Change settings mid-test: configure(TESSERACT_CMD="/nope")."""

    def _configure(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield _configure
    get_settings.cache_clear()
