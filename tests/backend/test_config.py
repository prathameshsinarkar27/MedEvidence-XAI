import pytest
from pydantic import ValidationError

from app.core.config import RESEARCH_DISCLAIMER, Settings


def _clean_settings(monkeypatch, **env) -> Settings:
    for key in ("DATABASE_URL", "LOG_LEVEL", "LOG_DIR", "CORS_ORIGINS", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_defaults_have_no_database_credentials(monkeypatch):
    settings = _clean_settings(monkeypatch)
    assert settings.database_url is None
    assert settings.app_env == "development"


def test_log_level_is_normalised(monkeypatch):
    assert _clean_settings(monkeypatch, LOG_LEVEL="debug").log_level == "DEBUG"


def test_invalid_log_level_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        _clean_settings(monkeypatch, LOG_LEVEL="LOUD")


def test_invalid_app_env_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        _clean_settings(monkeypatch, APP_ENV="staging")


def test_cors_origins_parsed(monkeypatch):
    settings = _clean_settings(monkeypatch, CORS_ORIGINS=" http://a.test , http://b.test ,,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_empty_log_dir_disables_file_logging(monkeypatch):
    assert _clean_settings(monkeypatch, LOG_DIR="").log_dir_path is None


def test_disclaimer_text():
    assert "research/educational prototype" in RESEARCH_DISCLAIMER
    assert "not a substitute for professional medical diagnosis or treatment" in RESEARCH_DISCLAIMER
