from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import ChatFeedback, ChatMessage, ChatSession, RewriteLabel, Student
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest, RewriteFeedbackRequest


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

        # 이전 대화 1세트 조회 (멀티턴 맥락 유지용)
        # 잡담(topic=general)은 건너뛰고 그 이전의 진짜 주제를 찾는다 — "안녕" 한마디로
        # 진행 중이던 RAG 대화 맥락(예: 휴학)이 끊기는 것을 방지 (잡담을 "투명하게" 취급)
        MAX_PREV_LENGTH = 200
        MAX_LOOKBACK = 20
        prev_context = None
        recent_msgs = (await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id, ChatMessage.id != user_msg.id)
            .order_by(ChatMessage.id.desc())
            .limit(MAX_LOOKBACK)
        )).scalars().all()
        for i, msg in enumerate(recent_msgs):
            if msg.role == "assistant" and msg.topic and msg.topic != "general":
                prev_answer = msg
                prev_question = next(
                    (m for m in recent_msgs[i + 1:] if m.role == "user"), None
                )
                if prev_question:
                    prev_context = {
                        "prev_question": prev_question.content[:MAX_PREV_LENGTH],
                        "prev_answer": prev_answer.content[:MAX_PREV_LENGTH],
                        "prev_topic": prev_answer.topic,
                    }
                break

        # 순환 import 방지를 위해 런타임에 가져온다.
        from app.agents.agent_graph import agent_graph

        result = await agent_graph.run(
            question=request.question,
            student_id=current_user.id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
            prev_context=prev_context,
            file_confirm=request.file_confirm,
        )

        # RAG 경로에서 질문이 재작성됐으면 원본 질문(user_msg) 행에 기록 (파인튜닝 데이터용)
        user_msg.rewritten_query = getattr(result, "rewritten_query", None)

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
            schedule_card=getattr(result, "schedule_card", None),
            pending_context=result.pending_context,
            rewritten_query=getattr(result, "rewritten_query", None),
        )

    async def get_my_sessions(self, db: AsyncSession, current_user: Student) -> list[dict]:
        """로그인 학생 본인의 최근 대화 목록 (사이드바용). topic은 필터용."""
        sessions = (await db.execute(
            select(ChatSession)
            .where(ChatSession.student_id == current_user.id, ChatSession.is_deleted == False)
            .order_by(ChatSession.last_message_at.desc())
            .limit(50)
        )).scalars().all()
        if not sessions:
            return []

        session_ids = [s.id for s in sessions]
        # 각 세션의 첫 assistant 메시지 topic (필터 기준)
        min_id_sub = (
            select(ChatMessage.session_id, func.min(ChatMessage.id).label("min_id"))
            .where(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "assistant")
            .group_by(ChatMessage.session_id)
            .subquery()
        )
        topic_rows = (await db.execute(
            select(ChatMessage.session_id, ChatMessage.topic)
            .join(min_id_sub, ChatMessage.id == min_id_sub.c.min_id)
        )).all()
        topic_map = {sid: topic for sid, topic in topic_rows}

        return [
            {
                "id": s.id,
                "title": s.title or "새 대화",
                "topic": topic_map.get(s.id),
                "last_message_at": s.last_message_at,
            }
            for s in sessions
        ]

    async def get_my_session_messages(self, db: AsyncSession, session_id: int, current_user: Student) -> dict:
        """과거 세션 다시 열기 — 본인 세션만 조회 가능."""
        session = await db.get(ChatSession, session_id)
        if not session or session.student_id != current_user.id or session.is_deleted:
            raise LookupError("세션을 찾을 수 없습니다.")
        msgs = (await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )).scalars().all()
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,        # user / assistant
                    "content": m.content,
                    "topic": m.topic,
                    "source": m.source,
                    "message_id": m.id,
                }
                for m in msgs
            ],
        }

    async def delete_my_session(self, db: AsyncSession, session_id: int, current_user: Student) -> dict:
        """대화 삭제 (soft delete) — 본인 세션만. is_deleted=True로 목록/조회에서 제외."""
        session = await db.get(ChatSession, session_id)
        if not session or session.student_id != current_user.id or session.is_deleted:
            raise LookupError("세션을 찾을 수 없습니다.")
        session.is_deleted = True
        await db.commit()
        return {"ok": True}

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

    async def save_rewrite_feedback(
        self,
        request: RewriteFeedbackRequest,
        db: AsyncSession,
        current_user: Student,
    ) -> dict:
        """개발용 rewrite 피드백 → rewrite_label 저장(파인튜닝 라벨).
        정답 라벨 = 좋으면 모델 rewrite 그대로, 나쁘면 교정값."""
        label = request.model_rewrite if request.is_good else (request.corrected or None)
        reviewer = getattr(current_user, "student_no", None) or str(current_user.id)

        existing = None
        if request.message_id is not None:
            existing = await db.scalar(
                select(RewriteLabel).where(RewriteLabel.message_id == request.message_id)
            )
        if existing:
            existing.question = request.question
            existing.prev_question = request.prev_question
            existing.model_rewrite = request.model_rewrite
            existing.label_rewrite = label
            existing.is_good = request.is_good
            existing.reviewer = reviewer
        else:
            db.add(RewriteLabel(
                message_id=request.message_id,
                question=request.question,
                prev_question=request.prev_question,
                model_rewrite=request.model_rewrite,
                label_rewrite=label,
                is_good=request.is_good,
                source="dev",
                reviewer=reviewer,
            ))
        await db.commit()
        return {"ok": True}

# 싱글톤 인스턴스
chat_service = ChatService()
