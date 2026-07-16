from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest, RewriteFeedbackRequest
from app.core.Database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import chat_rate_limit
from app.models.DB_Table import Student
from app.services.chat_service import chat_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(chat_rate_limit),
):
    try:
        return await chat_service.create_chat_response(request, db, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")


@router.get("/chat/sessions", summary="내 최근 대화 목록 (사이드바)")
async def my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    return await chat_service.get_my_sessions(db, current_user)


@router.get("/chat/sessions/{session_id}", summary="과거 대화 다시 열기")
async def my_session_messages(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.get_my_session_messages(db, session_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/chat/sessions/{session_id}", summary="대화 삭제 (soft delete)")
async def delete_my_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.delete_my_session(db, session_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/chat/feedback", summary="답변 피드백 (좋아요/싫어요)")
async def chat_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.save_feedback(request, db, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"피드백 저장 오류: {str(e)}")


@router.post("/chat/rewrite-feedback", summary="[개발용] rewrite 피드백 (파인튜닝 라벨)")
async def rewrite_feedback(
    request: RewriteFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.save_rewrite_feedback(request, db, current_user)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"rewrite 피드백 저장 오류: {str(e)}")
