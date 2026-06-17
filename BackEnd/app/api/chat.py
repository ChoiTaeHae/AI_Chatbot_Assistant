from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest
from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.chat_service import chat_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.create_chat_response(request, db, current_user)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")


@router.post("/chat/feedback", summary="답변 피드백 (좋아요/싫어요)")
async def chat_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.save_feedback(request, db)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"피드백 저장 오류: {str(e)}")
