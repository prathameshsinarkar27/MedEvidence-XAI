"""Evidence-grounded question answering (Phase 9): answer + confidence + claim-to-evidence mapping + explanation."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.qa import AnswerResponse, QAConfigOut
from app.services import qa as qa_service

router = APIRouter(prefix="/qa", tags=["qa"])


@router.get("/config", response_model=QAConfigOut, summary="Answer provider, abstention message and pipeline (the api key is never returned)")
def get_qa_config() -> QAConfigOut:
    return qa_service.qa_config(get_settings())


@router.get("/answer", response_model=AnswerResponse,
            summary="Question -> verified evidence -> grounded answer with citations, confidence and explanation (or abstention)")
def get_answer(
    q: str = Query(min_length=1, max_length=500),
    top_k: int | None = Query(default=None, ge=1),
    document_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
) -> AnswerResponse:
    settings = get_settings()
    question = q.strip()
    if not question:
        raise HTTPException(422, detail={"code": "empty_question", "message": "The question is empty."})
    if top_k is not None and top_k > settings.search_max_top_k:
        raise HTTPException(422, detail={"code": "top_k_too_large", "message": f"top_k must be at most {settings.search_max_top_k}."})
    return qa_service.answer(session, settings, question, top_k=top_k, document_id=document_id)
