from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import ChatFeedback, ChatMessage, ChatSession, Student
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest


class ChatService:
    async def create_chat_response(
        self,
        request: ChatRequest,
        db: AsyncSession,
        current_user: Student,
    ) -> ChatResponse:
        session = None

        if request.session_id:
            session = await db.get(ChatSession, request.session_id)
            if session and session.student_id != current_user.id:
                raise PermissionError("해당 세션에 접근할 수 없습니다.")
            if not session:
                session = None

        if not request.session_id or session is None:
            session = ChatSession(
                student_id=current_user.id,
                title=request.question[:100],
            )
            db.add(session)

        await db.flush()

        user_msg = ChatMessage(
            session_id=session.id,
            student_id=current_user.id,
            role="user",
            content=request.question,
        )
        db.add(user_msg)
        await db.flush()

        # 순환 import 방지를 위해 런타임에 가져온다.
        from app.agents.agent_graph import agent_graph

        result = await agent_graph.run(
            question=request.question,
            student_id=current_user.id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
            file_confirm=request.file_confirm,
        )

        asst_msg = ChatMessage(
            session_id=session.id,
            student_id=current_user.id,
            role="assistant",
            content=result.answer,
            intent=getattr(result, "intent", None),
            topic=getattr(result, "topic", None),
            source=getattr(result, "source", None),
            source_file=getattr(result, "source_file", None),
        )
        db.add(asst_msg)

        session.last_message_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(asst_msg)

        return ChatResponse(
            answer=result.answer,
            session_id=session.id,
            message_id=asst_msg.id,
            file_offer=result.file_offer,
            file_download=result.file_download,
            map_card=result.map_card,
            pending_context=result.pending_context,
        )

    async def save_feedback(
        self,
        request: FeedbackRequest,
        db: AsyncSession,
        current_user: Student,
    ) -> dict:
        message = await db.get(ChatMessage, request.message_id)
        if not message:
            raise LookupError("메시지를 찾을 수 없습니다.")
        if message.student_id != current_user.id:
            raise PermissionError("해당 메시지에 접근할 수 없습니다.")

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

# 싱글톤 인스턴스
chat_service = ChatService()
