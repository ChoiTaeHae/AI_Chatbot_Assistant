from fastapi import APIRouter, HTTPException
import traceback

from app.schemas.chat import ChatRequest, ChatResponse
from app.agents.school_agent import school_agent

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(request: ChatRequest):
    try:
        answer = await school_agent.run(request.question)
        return ChatResponse(answer=answer, session_id=request.session_id)
    except Exception as e:
        traceback.print_exc()   # 터미널에 상세 에러 출력
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
