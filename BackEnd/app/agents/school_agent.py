import asyncio
from app.agents.intent import IntentType
from app.agents.classifier import classify_intent
from app.agents.topic_router import topic_router
from app.services.chat_service import chat_service
from app.services.school.leave import answer_leave_question
from app.services.school.schedule import answer_schedule_question
from app.services.school.graduation import graduation_service
from app.services.school.campus import CampusService
from app.services.school.scholarship import answer_scholarship_question
from app.services.school.ot import answer_ot_question

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.school.special_credit import answer_special_credit_question

MAX_CONTEXT_LENGTH = 2000


campus_service = CampusService()


class SchoolAgent:
    """질문 의도를 파악해서 적절한 서비스로 라우팅하는 Agent"""

    async def run(self, question: str, student_id: int, db: AsyncSession) -> str:
        # 1단계: 키워드 매칭 (빠름, 0ms)
        intent = classify_intent(question)
        print(f"[Agent] 키워드 분류: {intent}")

        if intent != IntentType.GENERAL:
            return await self._dispatch(intent, question, student_id, db)

        # 2단계: 키워드 미매칭 → 임베딩 기반 topic 분류
        print("[Agent] 키워드 미매칭 → 임베딩 기반 topic 분류 시작")
        loop = asyncio.get_event_loop()
        routed = await loop.run_in_executor(None, topic_router.route, question)

        if routed is not None:
            print(f"[Agent] 임베딩 라우팅 → {routed}")
            return await self._dispatch(routed, question, student_id, db)

        # 3단계: 유사 topic 없음 → 진짜 일반 질문, RAG 없이 LLM 직접 호출
        print("[Agent] 일반 질문 → LLM 직접 호출")
        return await chat_service.answer(question)

    async def _dispatch(
        self, intent: IntentType, question: str, student_id: int, db: AsyncSession
    ) -> str:
        """intent → 해당 서비스 호출"""
        if intent == IntentType.GRADUATION:
            return await graduation_service.answer_graduation(
                question=question, student_id=student_id, db=db
            )
        elif intent == IntentType.SCHEDULE:
            return await answer_schedule_question(question)
        elif intent == IntentType.LEAVE:
            return await answer_leave_question(question)
        elif intent == IntentType.CAMPUS:
            return await self._handle_campus(question, db)
        elif intent == IntentType.SCHOLARSHIP:
            return await answer_scholarship_question(question, student_id=student_id, db=db)
        elif intent == IntentType.OT:
            return await answer_ot_question(question)
        elif intent == IntentType.SPECIAL_CREDIT:
            return await answer_special_credit_question(question)
        # 여기까지 오면 GENERAL이지만 안전망으로 LLM 직접 호출
        return await chat_service.answer(question)

    async def _handle_campus(self, question: str, db: AsyncSession) -> str:
        from app.agents.classifier import CAMPUS_KEYWORDS
        keyword = question
        for kw in CAMPUS_KEYWORDS:
            if kw in question:
                keyword = kw
                break
        result = await campus_service.search_location(question)
        return result.get("answer", "위치 정보를 찾을 수 없습니다.")


# 싱글톤 인스턴스
school_agent = SchoolAgent()

