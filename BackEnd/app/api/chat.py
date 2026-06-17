from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest
from app.agents.agent_graph import agent_graph
from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student, ChatSession, ChatMessage, ChatFeedback

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        # 1. 세션 조회 또는 생성
        if request.session_id:
            session = await db.get(ChatSession, request.session_id)
            if not session or session.student_id != current_user.id:
                session = None

        if not request.session_id or session is None:
            session = ChatSession(
                student_id=current_user.id,
                title=request.question[:100],
            )
            db.add(session)

        await db.flush()  # session.id 확보

        # 2. 유저 메시지 저장
        user_msg = ChatMessage(
            session_id=session.id,
            student_id=current_user.id,
            role="user",
            content=request.question,
        )
        db.add(user_msg)
        await db.flush()  # user_msg.id 확보

        # 3. 에이전트 실행 (내부에서 ChatLog 저장 + db.commit 수행)
        result = await agent_graph.run(
            question=request.question,
            student_id=current_user.id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
        )

        # 4. 어시스턴트 메시지 저장
        asst_msg = ChatMessage(
            session_id=session.id,
            student_id=current_user.id,
            role="assistant",
            content=result.answer,
        )
        db.add(asst_msg)

        # 5. 세션 최근 메시지 시각 갱신
        session.last_message_at = datetime.now(timezone.utc)

        await db.commit()

        return ChatResponse(
            answer=result.answer,
            session_id=session.id,
            message_id=asst_msg.id,
            file_offer=result.file_offer,
            file_download=result.file_download,
            map_card=result.map_card,
            pending_context=result.pending_context,
        )
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
        existing = await db.scalar(
            select(ChatFeedback).where(ChatFeedback.message_id == request.message_id)
        )
        if existing:
            existing.is_helpful = request.is_helpful
            existing.rating = request.rating
            existing.comment = request.comment
        else:
            db.add(ChatFeedback(
                message_id=request.message_id,
                is_helpful=request.is_helpful,
                rating=request.rating,
                comment=request.comment,
            ))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"피드백 저장 오류: {str(e)}")
