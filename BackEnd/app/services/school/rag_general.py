import asyncio

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT

def _resolve_topic(question: str) -> str | None:
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

    if "공결" in question or "출석인정" in question:
        return "absence"

    if "복수전공" in question or "부전공" in question:
        return "multi_major"

    if "전과" in question or "자퇴" in question or "재입학" in question:
        return "academic_status"

    if "학생지원" in question or "솔숲" in question or "오티" in question or "OT" in question or "카드" in question or "동아리" in question or "오리엔테이션" in question:
        return "student_support"

    if "ROTC" in question or "rotc" in question or "학군단" in question or "사관후보생" in question or "군사학" in question:
        return "rotc"

    # 매칭되는 키워드가 없으면 Qdrant가 전체 문서를 검색하도록 None 반환
    return None


def _search_rag(question: str) -> tuple[str, dict]:
    try:
        topic = _resolve_topic(question)

        print(
            f"[RAG_GENERAL] 선택된 topic: "
            f"{topic if topic else '전체 검색(None)'}"
        )

        # search 결과 + metadata용 result 함께 받기
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
            # MAX_CONTEXT_LENGTH 제거
            return context, metadata

    except Exception as e:
        print(f"[RAG_GENERAL] 검색 실패: {e}")

    return "", {
        "source": None,
        "source_file": None,
        "topic": _resolve_topic(question),
    }


async def answer_rag_general_question_with_metadata(question: str) -> tuple[str, dict]:
    print("[RAG_GENERAL] RAG 검색 시작")

    loop = asyncio.get_event_loop()

    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        question,
    )

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    is_club = "동아리" in question and _resolve_topic(question) == "student_support"
    _LIST_KEYWORDS = {"목록", "종류", "어떤", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}
    is_club_list = is_club and any(kw in question for kw in _LIST_KEYWORDS)
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, topic={_resolve_topic(question)}")
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


async def answer_rag_general_question(question: str) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question)
    return answer
