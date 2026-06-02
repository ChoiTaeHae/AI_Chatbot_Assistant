from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import chat_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(request: ChatRequest):
    """
    학교생활 관련 질문을 AI에게 전달하고 답변을 받습니다.

    - **question**: 질문 내용
    - **session_id**: 대화 세션 ID (선택, 추후 대화 기록 연동 시 사용)
    """
    try:
        answer = await chat_service.answer(request.question)
        return ChatResponse(answer=answer, session_id=request.session_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
