import asyncio

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT


async def _rewrite_query(question: str, topic_hint: str | None = None) -> str:
    """구어체 질문을 검색용 공식 용어로 변환. topic_hint가 있으면 질문 앞에 붙여 문맥 강제."""
    if topic_hint:
        question_with_topic = f"[{topic_hint}] {question}"
        prompt = QUERY_REWRITE_PROMPT.format(question=question_with_topic)
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

    # topic 코드 → 한국어 힌트 변환 (LLM이 영문 코드를 이해 못해서 검색어를 잘못 생성함)
    _TOPIC_KO = {
        "absence": "공결/출석인정",
        "course_registration": "수강신청",
        "leave": "휴학/복학",
        "scholarship": "장학금",
        "graduation": "졸업",
        "campus": "캠퍼스/건물 위치",
        "welfare_facilities": "복지시설",
        "student_support": "학생지원/동아리",
        "facility_rental": "시설대여",
        "academic_status": "학적/전과/자퇴",
    }
    topic_hint_ko = _TOPIC_KO.get(effective_topic) if effective_topic else None

    # "어떻게/방법/절차/순서" 포함 질문은 원본에 이미 핵심 키워드가 있어서 rewrite가 역효과
    _SKIP_REWRITE_KW = {"어떻게", "방법", "절차", "순서"}
    if any(kw in question for kw in _SKIP_REWRITE_KW):
        search_query = question
        print(f"[RAG_GENERAL] 절차형 질문 → rewrite 스킵, 원본 사용: '{question}'")
    else:
        search_query = await _rewrite_query(question, topic_hint=topic_hint_ko)

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        search_query,
        effective_topic,
    )

    # 검색 결과가 없으면 LLM 호출 스킵 — 근거 없는 답변(환각) 생성 방지
    if not context:
        print("[RAG_GENERAL] ⚠️ 검색 결과 0건 → LLM 호출 스킵, 안내 응답 반환")
        return (
            "죄송해요, 해당 내용에 대한 자료를 찾지 못했어요. "
            "조금 더 구체적으로 질문해 주시거나, "
            "학교 공식 홈페이지(wsu.ac.kr) 또는 담당 부서에 문의해 주세요.",
            metadata,
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

    # 모델이 프롬프트 레이블을 이어서 출력하는 경우 가장 앞에 나온 위치에서 잘라내기
    _STOP_MARKERS = ["[참고 문서]", "[사용자 질문]", "[답변]", "[이전 질문]", "[이전 답변]"]
    earliest_pos = len(answer)
    earliest_marker = None
    for marker in _STOP_MARKERS:
        pos = answer.find(marker)
        if pos != -1 and pos < earliest_pos:
            earliest_pos = pos
            earliest_marker = marker
    if earliest_marker:
        answer = answer[:earliest_pos].strip()
        print(f"[RAG_GENERAL] 프롬프트 누출 감지 → '{earliest_marker}' 앞에서 잘라냄")

    return answer, metadata


async def answer_rag_general_question(question: str, topic: str | None = None) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question, topic=topic)
    return answer
