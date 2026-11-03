"""Logging setup: console always, rotating file when LOG_DIR is set."""

import logging
import logging.config
from typing import Any

from app.core.config import Settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(settings: Settings) -> None:
    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": settings.log_level,
        }
    }

    log_dir = settings.log_dir_path
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "level": settings.log_level,
                "filename": str(log_dir / "backend.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            }
        except OSError as exc:  # fall back to console-only logging
            print(f"WARNING: file logging disabled ({exc})")

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": LOG_FORMAT}},
            "handlers": handlers,
            "root": {"level": settings.log_level, "handlers": list(handlers)},
        }
    )
