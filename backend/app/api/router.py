from fastapi import APIRouter

from app.api import documents, health, processing

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(processing.documents_router)
api_router.include_router(processing.system_router)
