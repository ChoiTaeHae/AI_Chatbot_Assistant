from app.aagentsintent import IntentType
from app.agents.classifier import classify_intent
from app.services.chat_service import chat_service


class SchoolAgent:
    """
    질문 의도를 파악해서 적절한 서비스로 라우팅하는 Agent
    """

    async def run(self, question: str) -> str:
        intent = classify_intent(question)
        print(f"[Agent] 질문: {question!r} → 의도: {intent}")

        if intent == IntentType.GRADUATION:
            return await self._handle_graduation(question)
        elif intent == IntentType.SCHEDULE:
            return await self._handle_schedule(question)
        else:
            return await self._handle_general(question)

    async def _handle_graduation(self, question: str) -> str:
        """졸업요건 관련 질문 처리"""
        # TODO: graduation_service 완성되면 데이터 조회 후 LLM에 전달
        # data = graduation_service.check_graduation(...)
        # context = f"졸업요건 데이터: {data}"
        # return await chat_service.answer_with_context(question, context)
        return await chat_service.answer(question)

    async def _handle_schedule(self, question: str) -> str:
        """학사일정 관련 질문 처리"""
        # TODO: schedule_service 완성되면 데이터 조회 후 LLM에 전달
        # data = schedule_service.get_schedule(...)
        # context = f"학사일정 데이터: {data}"
        # return await chat_service.answer_with_context(question, context)
        return await chat_service.answer(question)

    async def _handle_general(self, question: str) -> str:
        """일반 질문 처리"""
        return await chat_service.answer(question)


# 싱글톤 인스턴스
school_agent = SchoolAgent()
