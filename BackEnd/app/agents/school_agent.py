from app.agents.intent import IntentType
from app.agents.classifier import classify_intent
from app.services.chat_service import chat_service
from app.services.leave_service import answer_leave_question

from app.services.schedule_service import answer_schedule_question

from app.services.graduation_service import graduation_service
from sqlalchemy.ext.asyncio import AsyncSession


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
        else:
            return await self._handle_general(question)

    async def _handle_graduation(self, question: str , student_id: int , db: AsyncSession) -> str:
        # TODO: graduation_service 완성되면 연결
       return await graduation_service.answer_graduation(
            question=question, 
            student_id=student_id, 
            db=db
        )

    async def _handle_schedule(self, question: str) -> str:
        # TODO: schedule_service 완성되면 연결
        return await answer_schedule_question(question)

    async def _handle_general(self, question: str) -> str:
        return await chat_service.answer(question)


# 싱글톤 인스턴스
school_agent = SchoolAgent()
