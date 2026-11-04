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


# ---------- Phase 4 settings ----------

PHASE4_KEYS = (
    "IMAGE_DIR", "AUTO_MULTIMODAL", "IMAGE_OCR", "MIN_IMAGE_SIDE_PX", "MAX_IMAGES_PER_DOCUMENT",
    "MAX_TABLES_PER_DOCUMENT", "MAX_IMAGE_BYTES", "MAX_IMAGE_PIXELS", "MAX_CELLS_PER_TABLE", "IMAGE_OCR_MIN_CHARS",
)


def _phase4(monkeypatch, **env) -> Settings:
    for key in PHASE4_KEYS:
        monkeypatch.delenv(key, raising=False)
    return _clean_settings(monkeypatch, **env)


def test_phase4_defaults_are_safe(monkeypatch):
    settings = _phase4(monkeypatch)
    assert settings.auto_multimodal is True and settings.image_ocr is False  # image OCR must be opt-in
    assert settings.min_image_side_px == 32 and settings.max_images_per_document == 200
    assert settings.max_tables_per_document == 500 and settings.max_cells_per_table == 5000
    assert settings.max_image_bytes == 10 * 1024 * 1024 and settings.max_image_pixels == 50_000_000


def test_image_dir_resolves_against_the_repository_root_unless_absolute(monkeypatch, tmp_path):
    from app.core.config import REPO_ROOT

    assert _phase4(monkeypatch).image_dir_path == REPO_ROOT / "data" / "images"
    assert _phase4(monkeypatch, IMAGE_DIR=str(tmp_path)).image_dir_path == tmp_path


@pytest.mark.parametrize(
    "key, value",
    [("MIN_IMAGE_SIDE_PX", "0"), ("MAX_IMAGES_PER_DOCUMENT", "0"), ("MAX_IMAGE_BYTES", "10"),
     ("MAX_IMAGE_PIXELS", "5"), ("MAX_CELLS_PER_TABLE", "1"), ("IMAGE_OCR_MIN_CHARS", "0")],
)
def test_phase4_limits_reject_unreasonable_values(monkeypatch, key, value):
    with pytest.raises(ValidationError):
        _phase4(monkeypatch, **{key: value})


def test_processing_config_carries_the_phase4_settings(monkeypatch):
    config = _phase4(monkeypatch, IMAGE_OCR="true", MIN_IMAGE_SIDE_PX="64", MAX_CELLS_PER_TABLE="100",
                     IMAGE_OCR_MIN_CHARS="3").processing_config
    assert config.image_ocr is True and config.min_image_side_px == 64
    assert config.max_cells_per_table == 100 and config.image_ocr_min_chars == 3
