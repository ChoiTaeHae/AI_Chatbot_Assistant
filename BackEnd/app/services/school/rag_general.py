import asyncio
import math

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT, KEYWORD_EXTRACTION_SYSTEM_PROMPT

# 재작성 드리프트 임계값 — 원문과 재작성의 의미 유사도가 이 값 미만이면
# 환각(엉뚱한 주제로 변형)으로 보고 원본 질문을 사용한다. (bge-m3 코사인, 튜닝 가능)
_REWRITE_DRIFT_THRESHOLD = 0.5


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _is_semantic_drift(original: str, rewritten: str) -> bool:
    """재작성 결과가 원문과 의미상 너무 멀어졌는지(환각) 임베딩 유사도로 판단."""
    try:
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(
            None, rag_service.embedding.embed_texts, [original, rewritten]
        )
        sim = _cosine(vecs[0], vecs[1])
        print(f"[RAG_GENERAL] 재작성 의미 유사도={sim:.3f} (임계 {_REWRITE_DRIFT_THRESHOLD})")
        return sim < _REWRITE_DRIFT_THRESHOLD
    except Exception as e:
        # 검사 실패 시 재작성을 막지 않음 (검색 자체를 못하는 것보단 나음)
        print(f"[RAG_GENERAL] 드리프트 검사 실패(무시): {e}")
        return False


async def _rewrite_query(question: str) -> str:
    """구어체 질문을 검색용 공식 용어로 변환."""
    prompt = QUERY_REWRITE_PROMPT.format(question=question)
    rewritten = await llm_service.answer(
        prompt,
        max_tokens=64,
        system_prompt=KEYWORD_EXTRACTION_SYSTEM_PROMPT,
        temperature=0.0,   # 결정론적 출력으로 창의적 변형(환각) 억제
    )
    rewritten = rewritten.strip().splitlines()[0].strip()
    # LLM이 "입력:" 접두사를 그대로 출력하거나 원본과 동일한 경우 원본 사용
    if rewritten.startswith("입력:") or rewritten == question:
        print(f"[RAG_GENERAL] 질문 재작성 실패 → 원본 사용: '{question}'")
        return question
    # 드리프트 가드: 재작성이 원문과 의미가 너무 멀어지면(예: 공결→전과) 원본 사용
    if await _is_semantic_drift(question, rewritten):
        print(f"[RAG_GENERAL] 재작성 드리프트 감지 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
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
) -> tuple[str, dict]:
    """RAG 검색 후 LLM 답변 생성.

    topic: agent_graph에서 DB 라우팅으로 결정된 topic_name.
           None이면 전체 검색 (TopicRouter 미분류 — 분류 문장 보강 필요).
    """
    print("[RAG_GENERAL] RAG 검색 시작")

    effective_topic = topic
    if effective_topic is None:
        print("[RAG_GENERAL] ⚠️  TopicRouter 분류 실패 — topic=None, 전체 검색. 해당 질문의 분류 문장을 추가하세요.")
        print(f"[RAG_GENERAL] ⚠️  미분류 질문: {question}")

    # 구어체 질문을 공식 용어로 재작성 후 검색 (리랭커 점수 향상)
    search_query = await _rewrite_query(question)

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        search_query,
        effective_topic,
    )

    # 파인튜닝 데이터용: 실제로 재작성된 경우에만 기록 (원본과 같으면 no-op이므로 None)
    metadata["rewritten_query"] = search_query if search_query != question else None

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
