from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.agent.school_agent import school_agent

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(request: ChatRequest):
    try:
        answer = await school_agent.run(request.question)
        return ChatResponse(answer=answer, session_id=request.session_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
