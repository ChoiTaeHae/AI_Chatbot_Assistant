import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.school.special_credit import answer_special_credit_question

campus_service = CampusService()

# 긍정 응답 키워드
POSITIVE_KEYWORDS  = ["응", "네", "예", "ㅇㅇ", "보내줘", "보내", "좋아", "알겠어", "그래", "응응", "넹", "넵", "주세요"]
# 질문 의도 키워드 (긍정 오탐 방지)
QUESTION_KEYWORDS  = ["어떻게", "언제", "뭐야", "뭔데", "왜", "어디", "?", "？", "알려", "설명"]


@dataclass
class AgentResult:
    answer: str
    file_offer: dict | None = None       # { topic, filename }
    file_download: dict | None = None    # { topic, filename, url }
    map_card: dict | None = None         # { title, address, place_url, latitude, longitude }
    pending_context: dict | None = None  # { type: "scholarship" } 멀티턴 대화 상태


class SchoolAgent:
    """질문 의도를 파악해서 적절한 서비스로 라우팅하는 Agent"""

    async def run(
        self,
        question: str,
        student_id: int,
        db: AsyncSession,
        pending_file: dict | None = None,
        pending_context: dict | None = None,
    ) -> AgentResult:

        # 0단계: 파일 제안에 대한 긍정 응답 처리
        if pending_file and self._is_confirmation(question):
            return self._build_file_download(pending_file)

        # 0단계: 멀티턴 장학금 대화 처리 (GPA/소득분위 수집 중)
        if pending_context and pending_context.get("type") == "scholarship":
            answer, next_context = await answer_scholarship_question(
                question, student_id=student_id, db=db, pending_context=pending_context
            )
            return AgentResult(answer=answer, pending_context=next_context)

        # 1단계: 키워드 매칭 (빠름, 0ms)
        intent = classify_intent(question)
        print(f"[Agent] 키워드 분류: {intent}")

        if intent == IntentType.CAMPUS:
            return await self._handle_campus(question)

        if intent == IntentType.SCHOLARSHIP:
            answer, next_context = await answer_scholarship_question(question, student_id=student_id, db=db)
            return AgentResult(answer=answer, pending_context=next_context)

        if intent != IntentType.GENERAL:
            answer = await self._dispatch(intent, question, student_id, db)
            return self._with_file_offer(answer, intent.value)

        # 2단계: 임베딩 기반 topic 분류
        print("[Agent] 키워드 미매칭 → 임베딩 기반 topic 분류 시작")
        loop = asyncio.get_event_loop()
        routed = await loop.run_in_executor(None, topic_router.route, question)

        if routed is not None:
            print(f"[Agent] 임베딩 라우팅 → {routed}")
            if routed == IntentType.CAMPUS:
                return await self._handle_campus(question)
            if routed == IntentType.SCHOLARSHIP:
                answer, next_context = await answer_scholarship_question(question, student_id=student_id, db=db)
                return AgentResult(answer=answer, pending_context=next_context)
            answer = await self._dispatch(routed, question, student_id, db)
            return self._with_file_offer(answer, routed.value)

        # 3단계: 일반 질문 → LLM 직접 호출
        print("[Agent] 일반 질문 → LLM 직접 호출")
        return AgentResult(answer=await chat_service.answer(question))

    # ── 파일 관련 헬퍼 ────────────────────────────────────
    def _is_confirmation(self, text: str) -> bool:
        """긍정 응답인지 판단 (질문 키워드가 없을 때만 긍정으로 간주)"""
        if any(kw in text for kw in QUESTION_KEYWORDS):
            return False
        return any(kw in text for kw in POSITIVE_KEYWORDS)

    def _build_file_download(self, pending_file: dict) -> AgentResult:
        topic    = pending_file["topic"]
        filename = pending_file["filename"]
        stem     = Path(filename).stem
        return AgentResult(
            answer=f"네, {stem}을 보내드릴게요!",
            file_download={
                "topic":    topic,
                "filename": filename,
                "url":      f"/api/files/{topic}/{filename}",
            },
        )

    def _with_file_offer(self, answer: str, topic: str) -> AgentResult:
        """답변 끝에 파일 제안 추가. 해당 topic 파일이 없으면 그냥 answer 반환."""
        from app.services.file_service import AVAILABLE_FILES
        files = AVAILABLE_FILES.get(topic, [])
        if not files:
            return AgentResult(answer=answer)
        filename = files[0]
        stem     = Path(filename).stem
        return AgentResult(
            answer=answer + f"\n\n혹시 **{stem}** 파일이 필요하시면 보내드릴까요?",
            file_offer={"topic": topic, "filename": filename},
        )

    # ── 서비스 라우팅 ─────────────────────────────────────
    async def _dispatch(
        self, intent: IntentType, question: str, student_id: int, db: AsyncSession
    ) -> str:
        if intent == IntentType.GRADUATION:
            return await graduation_service.answer_graduation(
                question=question, student_id=student_id, db=db
            )
        elif intent == IntentType.SCHEDULE:
            return await answer_schedule_question(question)
        elif intent == IntentType.LEAVE:
            return await answer_leave_question(question)
        elif intent == IntentType.OT:
            return await answer_ot_question(question)
        elif intent == IntentType.SPECIAL_CREDIT:
            return await answer_special_credit_question(question)
        # 안전망
        return await chat_service.answer(question)

    async def _handle_campus(self, question: str) -> AgentResult:
        result = await campus_service.search_location(question)
        answer = result.get("answer", "위치 정보를 찾을 수 없습니다.")
        map_card = result.get("map_card") if result.get("found") else None
        return AgentResult(answer=answer, map_card=map_card)


# 싱글톤 인스턴스
school_agent = SchoolAgent()
