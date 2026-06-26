import asyncio

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT


def _keyword_topic(question: str) -> str | None:
    """키워드 기반 topic 추론 — DB 라우팅 실패 시 fallback."""
    q = question.lower()
    if "휴학" in q or "복학" in q:
        return "leave"
    if "기숙사" in q or "생활관" in q:
        return "dormitory"
    if "수강신청" in q:
        return "course_registration"
    if "특별학점" in q:
        return "special_credit"
    if "성적" in q or "학점" in q or "gpa" in q:
        return "grades"
    if "학칙" in q or "규정" in q or "규칙" in q:
        return "school_rules"
    if "공결" in q or "출석인정" in q:
        return "absence"
    if "복수전공" in q or "부전공" in q:
        return "multi_major"
    if "전과" in q or "자퇴" in q or "재입학" in q:
        return "academic_status"
    if "학생지원" in q or "솔숲" in q or "오티" in q or "ot" in q or "카드" in q or "동아리" in q or "오리엔테이션" in q:
        return "student_support"
    if "rotc" in q or "학군단" in q or "사관후보생" in q or "군사학" in q:
        return "rotc"
    return None


def _search_rag(question: str, topic: str | None) -> tuple[str, dict]:
    """Qdrant 검색. topic이 None이면 전체 검색."""
    try:
        print(
            f"[RAG_GENERAL] 선택된 topic: "
            f"{topic if topic else '전체 검색(None)'}"
        )

        context, results = rag_service.search_context_with_results(
            question,
            topic=topic,
        )

        metadata = rag_service.primary_metadata(
            results,
            topic=topic,
        )

        print(f"[RAG] context length = {len(context)} chars")
        print(f"[RAG] retrieved chunks = {len(results)}")

        for i, result in enumerate(results, start=1):
            print(
                f"[Chunk {i}] "
                f"score={result.score:.3f}, "
                f"length={len(result.text)}"
            )

        print("\n========== RAG CONTEXT ==========")
        print(context)
        print("=================================\n")

        if context:
            return context, metadata

    except Exception as e:
        print(f"[RAG_GENERAL] 검색 실패: {e}")

    return "", {
        "source": None,
        "source_file": None,
        "topic": topic,
    }


async def answer_rag_general_question_with_metadata(
    question: str,
    topic: str | None = None,
) -> tuple[str, dict]:
    """RAG 검색 후 LLM 답변 생성.

    topic: agent_graph에서 DB 라우팅으로 결정된 topic_name.
           None이면 키워드 fallback → 그래도 없으면 전체 검색.
    """
    print("[RAG_GENERAL] RAG 검색 시작")

    # topic 우선순위: 라우팅 결과 → 키워드 fallback → None(전체 검색)
    effective_topic = topic or _keyword_topic(question)

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        question,
        effective_topic,
    )

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    is_club = "동아리" in question and effective_topic == "student_support"
    _LIST_KEYWORDS = {"목록", "종류", "어떤", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}
    is_club_list = is_club and any(kw in question for kw in _LIST_KEYWORDS)
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, topic={effective_topic}")

    if is_club_list:
        prompt = RAG_CLUB_LIST_PROMPT.format(context=context)
        answer = await llm_service.answer(prompt, max_tokens=2048)
    elif is_club:
        prompt = RAG_CLUB_DETAIL_PROMPT.format(context=context, question=question)
        answer = await llm_service.answer(prompt, max_tokens=1024)
    else:
        prompt = RAG_GENERAL_PROMPT.format(context=context, question=question)
        answer = await llm_service.answer(prompt)

    return answer, metadata


async def answer_rag_general_question(question: str, topic: str | None = None) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question, topic=topic)
    return answer
