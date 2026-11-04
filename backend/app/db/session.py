"""Database engine/session management and connectivity check."""

import logging
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseStatus:
    status: str  # "connected" | "unreachable" | "not_configured"
    detail: str
    server_version: str | None = None


@lru_cache
def get_engine() -> Engine | None:
    """Return the shared engine, or None if DATABASE_URL is not configured."""
    url = get_settings().database_url
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def get_session_factory() -> sessionmaker:
    """FastAPI dependency returning a session factory (503 if DATABASE_URL is not configured).

    Background tasks use this to open their own sessions: a request-scoped session is closed
    once the response is sent.
    """
    engine = get_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "database_not_configured", "message": "The database is not configured."},
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """FastAPI dependency yielding a DB session (503 if DATABASE_URL is not configured)."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def safe_database_label() -> str | None:
    """Host/port/database of the configured URL, with credentials omitted."""
    url = get_settings().database_url
    if not url:
        return None
    try:
        parsed = make_url(url)
    except Exception:  # malformed URL; never echo it back
        return None
    return f"{parsed.host or 'localhost'}:{parsed.port or 5432}/{parsed.database}"


def check_database() -> DatabaseStatus:
    """Probe PostgreSQL connectivity. Never raises; never leaks credentials."""
    engine = get_engine()
    if engine is None:
        return DatabaseStatus("not_configured", "DATABASE_URL is not set")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
        return DatabaseStatus("connected", "PostgreSQL connection OK", str(version))
    except SQLAlchemyError as exc:
        logger.warning("Database check failed: %s", type(exc).__name__)
        return DatabaseStatus("unreachable", f"Cannot connect ({type(exc.__cause__ or exc).__name__})")
