import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intent import IntentType
from app.agents.topic_router import topic_router

from app.services.chat_service import chat_service
from app.services.school.graduation import graduation_service
from app.services.school.campus import CampusService
from app.services.school.rag_general import answer_rag_general_question


campus_service = CampusService()


class SchoolAgent:
    """질문 의도를 파악해서 적절한 서비스로 라우팅"""

    async def run(
        self,
        question: str,
        student_id: int,
        db: AsyncSession,
    ) -> str:

        print("[Agent] 임베딩 기반 topic 분류 시작")

        loop = asyncio.get_event_loop()

        intent = await loop.run_in_executor(
            None,
            topic_router.route,
            question,
        )

        if intent is None:
            intent = IntentType.GENERAL

        print(f"[Agent] 최종 intent → {intent}")

        return await self._dispatch(
            intent=intent,
            question=question,
            student_id=student_id,
            db=db,
        )

    async def _dispatch(
        self,
        intent: IntentType,
        question: str,
        student_id: int,
        db: AsyncSession,
    ) -> str:

        if intent == IntentType.GRADUATION:
            return await graduation_service.answer_graduation(
                question=question,
                student_id=student_id,
                db=db,
            )

        elif intent == IntentType.CAMPUS:
            return await self._handle_campus(question)

        elif intent == IntentType.RAG_GENERAL:
            return await answer_rag_general_question(question)

        # GENERAL
        return await chat_service.answer(question)

    async def _handle_campus(self, question: str) -> str:

        result = await campus_service.search_location(question)

        return result.get(
            "answer",
            "위치 정보를 찾을 수 없습니다."
        )


# 싱글톤
school_agent = SchoolAgent()