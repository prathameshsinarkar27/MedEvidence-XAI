from fastapi import APIRouter

from app.api import clinical, documents, evidence, health, multimodal, processing, reasoning

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(processing.documents_router)
api_router.include_router(processing.system_router)
api_router.include_router(multimodal.router)
api_router.include_router(clinical.router)
api_router.include_router(evidence.documents_router)
api_router.include_router(evidence.router)
api_router.include_router(reasoning.router)
