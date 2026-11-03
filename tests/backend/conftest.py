import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_engine


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
