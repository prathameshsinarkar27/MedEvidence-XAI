"""Application configuration.

All settings come from environment variables (optionally loaded from a `.env`
file in the repository root). No secrets or credentials are hard-coded.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    def log_dir_path(self) -> Path | None:
        if not self.log_dir:
            return None
        path = Path(self.log_dir)
        return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
