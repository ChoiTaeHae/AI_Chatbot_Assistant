from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse
from app.agents.school_agent import school_agent
from app.core.Database import get_db


router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        #로그인 시스템 결합 전 임시 테스트용 PK ID
        test_student_id = 1 


        answer = await school_agent.run(
            question=request.question)
        return ChatResponse(answer=answer, session_id=request.session_id)
    
    except Exception as e:
        traceback.print_exc()   # 터미널에 상세 에러 출력
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
