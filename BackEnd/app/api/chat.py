from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse
from app.agents.school_agent import school_agent
from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        result = await school_agent.run(
            question=request.question,
            student_id=current_user.id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
        )
        return ChatResponse(
            answer=result.answer,
            session_id=request.session_id,
            file_offer=result.file_offer,
            file_download=result.file_download,
            map_card=result.map_card,
            pending_context=result.pending_context,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
