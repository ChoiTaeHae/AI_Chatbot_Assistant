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
            if not session or session.student_id != current_user.id:
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
        from app.agents.school_agent import school_agent

        result = await school_agent.run(
            question=request.question,
            student_id=current_user.id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
        )

        asst_msg = ChatMessage(
            session_id=session.id,
            student_id=current_user.id,
            role="assistant",
            content=result.answer,
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
    ) -> dict:
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

    def _classify(self, question: str) -> str:
        """짧은 분류 프롬프트로 intent 이름 반환 (campus/graduation/rag_general/general)"""
        if settings.DEV_MODE or self.model is None:
            return "general"

        prompt = (
            "다음 질문을 아래 카테고리 중 하나로만 분류하세요. 카테고리 이름 외에는 절대 출력하지 마세요.\n\n"
            "카테고리:\n"
            "- campus: 건물 위치, 강의실, 캠퍼스 시설, 학과 사무실\n"
            "- graduation: 졸업요건, 졸업학점, 이수조건\n"
            "- rag_general: 장학금, 수강신청, 학사일정, 동아리, 기숙사, 휴학, 학칙, 증명서\n"
            "- general: 위 카테고리에 해당하지 않는 일반 대화\n\n"
            f"질문: {question}\n"
            "카테고리:"
        )
        try:
            response = self.model.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )
            return response["choices"][0]["message"]["content"].strip().lower()
        except Exception as e:
            print(f"[LLMClassify] 분류 실패: {e}")
            return "general"

    async def classify_intent(self, question: str) -> str:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(_executor, self._classify, question)
        return _parse_llm_intent(raw)


_VALID_INTENTS = {"campus", "graduation", "rag_general", "general"}


def _parse_llm_intent(text: str) -> str:
    text = text.strip().lower().replace(" ", "").replace("-", "")
    for intent in _VALID_INTENTS:
        if intent.replace("_", "") in text:
            return intent
    if "캠퍼스" in text or "건물" in text or "위치" in text:
        return "campus"
    if "졸업" in text:
        return "graduation"
    if "장학" in text or "수강" in text or "기숙" in text or "동아리" in text or "휴학" in text:
        return "rag_general"
    return "general"


# 싱글톤 인스턴스
chat_service = ChatService()
