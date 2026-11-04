"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app import __version__
from app.api.router import api_router
from app.core.config import RESEARCH_DISCLAIMER, get_settings
from app.core.logging import configure_logging
from app.core.middleware import UploadSizeLimitMiddleware
from app.db.session import get_engine
from app.services import processing as processing_service
from app.services.upload_validation import UploadValidationError

logger = logging.getLogger(__name__)


def _recover_interrupted_processing() -> None:
    """Documents left queued/processing by a previous run can never finish; mark them failed."""
    try:
        engine = get_engine()
        if engine is None:
            return
        count = processing_service.recover_interrupted(sessionmaker(bind=engine))
        if count:
            logger.warning("Marked %d interrupted document(s) as failed", count)
    except Exception as exc:  # database may be down or not yet migrated; health endpoint reports that
        logger.warning("Skipped interrupted-processing recovery (%s)", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    logger.info("Starting %s v%s (env=%s)", settings.app_name, __version__, settings.app_env)
    if not settings.database_url:
        logger.warning("DATABASE_URL is not set; database features are unavailable")
    else:
        _recover_interrupted_processing()
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=RESEARCH_DISCLAIMER,
        lifespan=lifespan,
    )
    app.add_middleware(UploadSizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(UploadValidationError)
    async def _upload_validation_handler(_: Request, exc: UploadValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(api_router)
    return app


app = create_app()
