import asyncio

from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

MAX_CONTEXT_LENGTH = 1000


def _resolve_topic(question: str) -> str:
    question = question.lower()

    if "휴학" in question or "복학" in question:
        return "leave"

    if "기숙사" in question or "생활관" in question:
        return "dormitory"

    if "수강신청" in question:
        return "course_registration"

    if "특별학점" in question:
        return "special_credit"

    if "성적" in question or "학점" in question or "gpa" in question:
        return "grades"

    if "학칙" in question or "규정" in question or "규칙" in question:
        return "school_rules"

    return "general"


def _search_rag(question: str) -> str:
    try:
        topic = _resolve_topic(question)

        print(f"[RAG_GENERAL] 선택된 topic: {topic}")

        context = rag_service.search_context(
            question,
            # topic=topic,
        )

        print("\n========== RAG CONTEXT ==========")
        print(context)
        print("=================================\n")

        if context:
            return context[:MAX_CONTEXT_LENGTH]

    except Exception as e:
        print(f"[RAG_GENERAL] 검색 실패: {e}")

    return ""


async def answer_rag_general_question(question: str) -> str:
    print("[RAG_GENERAL] RAG 검색 시작")

    loop = asyncio.get_event_loop()

    context = await loop.run_in_executor(
        None,
        _search_rag,
        question,
    )

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    prompt = f"""
규칙:
- 사용자의 질문에 바로 답변한다.
- 인사말을 하지 않는다.
- 자기소개를 하지 않는다.
- "궁금한 점이 있으신가요?"와 같은 추가 질문을 하지 않는다.
- 참고 문서에 있는 내용만 근거로 답변한다.
- 문서에 없는 일정, 기간, 비용, 운영 여부는 추측하지 않는다.
- 필요한 경우 공식 홈페이지, 대학정보시스템, 학과사무실 또는 담당 부서 확인을 안내한다.
- 답변은 간결하고 자연스러운 한국어로 작성한다.

[참고 문서]
{context}

[사용자 질문]
{question}

[답변]
"""

    return await chat_service.answer(prompt)