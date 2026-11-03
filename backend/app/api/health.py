"""Health-check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app import __version__
from app.core.config import RESEARCH_DISCLAIMER, get_settings
from app.db.session import check_database, safe_database_label

router = APIRouter(prefix="/health", tags=["health"])


class DatabaseHealth(BaseModel):
    status: str
    detail: str
    server_version: str | None = None
    target: str | None = None  # host:port/db, never credentials


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    app_name: str
    version: str
    environment: str
    timestamp: datetime
    database: DatabaseHealth
    disclaimer: str = RESEARCH_DISCLAIMER


def _build_response() -> HealthResponse:
    settings = get_settings()
    db = check_database()
    return HealthResponse(
        status="ok" if db.status == "connected" else "degraded",
        app_name=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        timestamp=datetime.now(timezone.utc),
        database=DatabaseHealth(
            status=db.status,
            detail=db.detail,
            server_version=db.server_version,
            target=safe_database_label(),
        ),
    )


@router.get("", response_model=HealthResponse, summary="Liveness + dependency status")
def health() -> HealthResponse:
    """Always 200 while the API process is up; `status` is `degraded` if the DB is down."""
    return _build_response()


@router.get("/ready", response_model=HealthResponse, summary="Readiness (503 if DB unavailable)")
def ready(response: Response) -> HealthResponse:
    result = _build_response()
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
