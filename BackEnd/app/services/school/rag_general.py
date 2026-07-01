import asyncio

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT, QUERY_REWRITE_WITH_TOPIC_PROMPT


async def _rewrite_query(question: str, topic_hint: str | None = None) -> str:
    """구어체 질문을 검색용 공식 용어로 변환. topic_hint가 있으면 주제 맥락 포함."""
    if topic_hint:
        prompt = QUERY_REWRITE_WITH_TOPIC_PROMPT.format(topic=topic_hint, question=question)
    else:
        prompt = QUERY_REWRITE_PROMPT.format(question=question)
    rewritten = await llm_service.answer(prompt, max_tokens=64)
    rewritten = rewritten.strip().splitlines()[0].strip()
    # LLM이 "입력:" 접두사를 그대로 출력하거나 원본과 동일한 경우 원본 사용
    if rewritten.startswith("입력:") or rewritten == question:
        print(f"[RAG_GENERAL] 질문 재작성 실패 → 원본 사용: '{question}'")
        return question
    print(f"[RAG_GENERAL] 질문 재작성: '{question}' → '{rewritten}'")
    return rewritten


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
    context_question: str | None = None,
) -> tuple[str, dict]:
    """RAG 검색 후 LLM 답변 생성.

    question: Qdrant 검색 및 query rewrite용 원본 질문 (이전 대화 prefix 없음)
    topic: agent_graph에서 DB 라우팅으로 결정된 topic_name.
           None이면 전체 검색 (TopicRouter 미분류 — 분류 문장 보강 필요).
    context_question: LLM 프롬프트용 질문 (이전 대화 prefix 포함). None이면 question 사용.
    """
    print("[RAG_GENERAL] RAG 검색 시작")

    effective_topic = topic
    if effective_topic is None:
        print("[RAG_GENERAL] ⚠️  TopicRouter 분류 실패 — topic=None, 전체 검색. 해당 질문의 분류 문장을 추가하세요.")
        print(f"[RAG_GENERAL] ⚠️  미분류 질문: {question}")

    # 원본 질문 + topic 힌트로 재작성 — enriched question을 넘기면 LLM이 이전 답변을 검색어로 오해함
    search_query = await _rewrite_query(question, topic_hint=effective_topic)

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        search_query,
        effective_topic,
    )

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    # LLM에는 이전 대화 맥락이 포함된 질문 전달
    llm_question = context_question if context_question is not None else question

    is_club = "동아리" in llm_question and effective_topic == "student_support"
    _LIST_KEYWORDS = {"목록", "종류", "어떤", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}
    is_club_list = is_club and any(kw in llm_question for kw in _LIST_KEYWORDS)
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, topic={effective_topic}")

    if is_club_list:
        prompt = RAG_CLUB_LIST_PROMPT.format(context=context)
        answer = await llm_service.answer(prompt, max_tokens=2048)
    elif is_club:
        prompt = RAG_CLUB_DETAIL_PROMPT.format(context=context, question=llm_question)
        answer = await llm_service.answer(prompt, max_tokens=1024)
    else:
        prompt = RAG_GENERAL_PROMPT.format(context=context, question=llm_question)
        answer = await llm_service.answer(prompt)

    return answer, metadata


async def answer_rag_general_question(question: str, topic: str | None = None) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question, topic=topic)
    return answer
