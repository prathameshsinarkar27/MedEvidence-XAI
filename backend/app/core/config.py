"""Application configuration.

All settings come from environment variables (optionally loaded from a `.env`
file in the repository root). No secrets or credentials are hard-coded.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from document_processing import ProcessingConfig  # repo root is put on sys.path by app/__init__.py

# backend/app/core/config.py -> repository root is three levels above `app/`
REPO_ROOT = Path(__file__).resolve().parents[3]

RESEARCH_DISCLAIMER = (
    "This is a research/educational prototype and is not a substitute for "
    "professional medical diagnosis or treatment."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MedEvidence-XAI"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_dir: str = "logs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:PASSWORD@host:5432/dbname
    # Intentionally has no default: credentials must come from the environment.
    database_url: str | None = Field(default=None)

    # 2: document upload. Files are stored under UPLOAD_DIR (relative paths
    # are resolved against the repository root).
    upload_dir: str = "data/uploads"
    max_upload_size_mb: int = Field(default=25, ge=1, le=200)

    # 3: PDF text extraction + OCR.
    tesseract_cmd: str | None = None  # full path to the tesseract binary if it is not on PATH
    ocr_languages: str = "eng"  # Tesseract codes joined with "+", e.g. "eng+hin"
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    ocr_timeout_seconds: int = Field(default=60, ge=5, le=600)
    min_text_chars_per_page: int = Field(default=25, ge=1, le=1000)
    max_pdf_pages: int = Field(default=300, ge=1, le=2000)

    @field_validator("ocr_languages")
    @classmethod
    def _validate_ocr_languages(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*", value):
            raise ValueError("OCR_LANGUAGES must look like 'eng' or 'eng+hin'")
        return value

    @field_validator("tesseract_cmd")
    @classmethod
    def _blank_tesseract_cmd_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid LOG_LEVEL: {value!r}")
        return level

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def processing_config(self) -> ProcessingConfig:
        return ProcessingConfig(
            min_text_chars=self.min_text_chars_per_page,
            ocr_languages=self.ocr_languages,
            ocr_dpi=self.ocr_dpi,
            ocr_timeout_seconds=self.ocr_timeout_seconds,
            max_pages=self.max_pdf_pages,
            tesseract_cmd=self.tesseract_cmd,
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_dir_path(self) -> Path:
        path = Path(self.upload_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def log_dir_path(self) -> Path | None:
        if not self.log_dir:
            return None
        path = Path(self.log_dir)
        return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
