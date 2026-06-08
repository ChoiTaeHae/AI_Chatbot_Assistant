from app.agents.intent import IntentType
from app.agents.classifier import classify_intent
from app.services.chat_service import chat_service
from app.services.school.leave import answer_leave_question
from app.services.school.schedule import answer_schedule_question
from app.services.school.graduation import graduation_service
from app.services.school.campus import CampusService
from sqlalchemy.ext.asyncio import AsyncSession

campus_service = CampusService()


class SchoolAgent:
    """질문 의도를 파악해서 적절한 서비스로 라우팅하는 Agent"""

    async def run(self, question: str, student_id: int, db: AsyncSession) -> str:
        intent = classify_intent(question)
        print(f"[Agent] 의도: {intent}")

        if intent == IntentType.GRADUATION:
            return await self._handle_graduation(question, student_id, db)
        elif intent == IntentType.SCHEDULE:
            return await self._handle_schedule(question)
        elif intent == IntentType.LEAVE:
            return await answer_leave_question(question)
        elif intent == IntentType.CAMPUS:
            return await self._handle_campus(question, db)
        else:
            return await self._handle_general(question)

    async def _handle_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        return await graduation_service.answer_graduation(
            question=question,
            student_id=student_id,
            db=db
        )

    async def _handle_schedule(self, question: str) -> str:
        return await answer_schedule_question(question)

    async def _handle_campus(self, question: str, db: AsyncSession) -> str:
        # 질문에서 CAMPUS 키워드 추출
        from app.agents.classifier import CAMPUS_KEYWORDS
        keyword = question
        for kw in CAMPUS_KEYWORDS:
            if kw in question:
                keyword = kw
                break
        result = await campus_service.search_location(db, keyword)
        return result.get("msg", "위치 정보를 찾을 수 없습니다.")

    async def _handle_general(self, question: str) -> str:
        return await chat_service.answer(question)


# 싱글톤 인스턴스
school_agent = SchoolAgent()

