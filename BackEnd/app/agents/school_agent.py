```python
import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intent import IntentType
from app.agents.topic_router import topic_router
from app.services.chat_service import chat_service
from app.services.school.campus import CampusService
from app.services.school.graduation import graduation_service
from app.services.school.rag_general import answer_rag_general_question

campus_service = CampusService()

# 긍정 응답 키워드
POSITIVE_KEYWORDS = [
    "응", "네", "예", "ㅇㅇ", "보내줘", "보내",
    "좋아", "알겠어", "그래", "응응", "넹", "넵", "주세요"
]

# 질문 의도 키워드 (긍정 오탐 방지)
QUESTION_KEYWORDS = [
    "어떻게", "언제", "뭐야", "뭔데", "왜", "어디", "?", "？", "알려", "설명"
]


@dataclass
class AgentResult:
    answer: str
    file_offer: dict | None = None
    file_download: dict | None = None
    map_card: dict | None = None


class SchoolAgent:
    """질문 의도를 파악해서 적절한 서비스로 라우팅"""

    async def run(
        self,
        question: str,
        student_id: int,
        db: AsyncSession,
        pending_file: dict | None = None,
    ) -> AgentResult:

        # 파일 제안에 대한 긍정 응답 처리
        if pending_file and self._is_confirmation(question):
            return self._build_file_download(pending_file)

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

        if intent == IntentType.CAMPUS:
            return await self._handle_campus(question)

        answer = await self._dispatch(
            intent=intent,
            question=question,
            student_id=student_id,
            db=db,
        )

        return self._with_file_offer(answer, intent.value)

    # ───────────────── 파일 관련 ─────────────────

    def _is_confirmation(self, text: str) -> bool:
        if any(kw in text for kw in QUESTION_KEYWORDS):
            return False

        return any(kw in text for kw in POSITIVE_KEYWORDS)

    def _build_file_download(self, pending_file: dict) -> AgentResult:
        topic = pending_file["topic"]
        filename = pending_file["filename"]
        stem = Path(filename).stem

        return AgentResult(
            answer=f"네, {stem}을 보내드릴게요!",
            file_download={
                "topic": topic,
                "filename": filename,
                "url": f"/api/files/{topic}/{filename}",
            },
        )

    def _with_file_offer(self, answer: str, topic: str) -> AgentResult:
        from app.services.file_service import AVAILABLE_FILES

        files = AVAILABLE_FILES.get(topic, [])

        if not files:
            return AgentResult(answer=answer)

        filename = files[0]
        stem = Path(filename).stem

        return AgentResult(
            answer=answer + f"\n\n혹시 **{stem}** 파일이 필요하시면 보내드릴까요?",
            file_offer={
                "topic": topic,
                "filename": filename,
            },
        )

    # ───────────────── 서비스 라우팅 ─────────────────

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

        elif intent == IntentType.RAG_GENERAL:
            return await answer_rag_general_question(question)

        # GENERAL
        return await chat_service.answer(question)

    async def _handle_campus(self, question: str) -> AgentResult:

        result = await campus_service.search_location(question)

        answer = result.get(
            "answer",
            "위치 정보를 찾을 수 없습니다."
        )

        map_card = result.get("map_card") if result.get("found") else None

        return AgentResult(
            answer=answer,
            map_card=map_card,
        )


# 싱글톤
school_agent = SchoolAgent()
```
