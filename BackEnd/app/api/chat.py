from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import traceback

from app.schemas.chat import ChatRequest, ChatResponse
from app.agents.school_agent import school_agent
from app.core.Database import get_db

router = APIRouter()


async def get_student_id(student_no: str | None, db: AsyncSession) -> int:
    """학번으로 student_id 조회. 없으면 기본값 1 반환"""
    if not student_no:
        return 1
    try:
        result = await db.execute(
            text("SELECT id FROM student WHERE student_no = :sno"),
            {"sno": student_no}
        )
        row = result.fetchone()
        return row.id if row else 1
    except Exception:
        return 1


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        student_id = await get_student_id(request.student_no, db)

        answer = await school_agent.run(
            question=request.question,
            student_id=student_id,
            db=db
        )
        return ChatResponse(answer=answer, session_id=request.session_id)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")
