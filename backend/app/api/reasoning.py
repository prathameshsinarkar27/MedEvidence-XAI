"""Question understanding and evidence verification endpoints (Phase 8). No answer generation (Phase 9)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.reasoning import QuestionUnderstandingOut, ReasoningConfigOut, VerificationResponse
from app.services import reasoning as reasoning_service

router = APIRouter(prefix="/reasoning", tags=["reasoning"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _clean(q: str) -> str:
    question = q.strip()
    if not question:
        raise _error(422, "empty_question", "The question is empty.")
    return question


@router.get("/config", response_model=ReasoningConfigOut, summary="Verification formula, weights, thresholds and conflict tolerances")
def get_reasoning_config() -> ReasoningConfigOut:
    return reasoning_service.reasoning_config(get_settings())


@router.get("/understand", response_model=QuestionUnderstandingOut,
            summary="Question understanding only: types, entities, dates, constraints, requested information")
def understand(q: str = Query(min_length=1, max_length=500)) -> QuestionUnderstandingOut:
    return reasoning_service.understand(_clean(q))


@router.get("/verify", response_model=VerificationResponse,
            summary="Question -> retrieved evidence -> ranked evidence -> verification -> conflict analysis -> evidence state")
def verify(
    q: str = Query(min_length=1, max_length=500),
    top_k: int | None = Query(default=None, ge=1, description="Evidence items to retrieve (default VERIFY_CANDIDATES)"),
    document_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
) -> VerificationResponse:
    settings = get_settings()
    question = _clean(q)
    if top_k is not None and top_k > settings.search_max_top_k:
        raise _error(422, "top_k_too_large", f"top_k must be at most {settings.search_max_top_k}.")
    return reasoning_service.verify(session, settings, question, top_k=top_k, document_id=document_id)
