import asyncio
import math
import re

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT, QUERY_REWRITE_WITH_CONTEXT_PROMPT, KEYWORD_EXTRACTION_SYSTEM_PROMPT

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


# 주제를 식별하지 못하는 일반어 — 아래 주제어 검사에서 제외한다.
# (접두 일치로 비교하므로 '얼마야'는 '얼마', '신청은'은 '신청'으로 걸러진다)
_GENERIC_TERMS = (
    "신청", "방법", "알려줘", "어떻게", "언제", "얼마", "기간", "일정", "안내", "문의",
    "절차", "서류", "가능", "필요", "준비", "무엇", "무슨", "어디", "해줘", "되나요",
    "인가요", "있어", "있나요", "하나요", "까지", "부터", "궁금", "확인", "조건", "기준",
    "대해서", "관련", "이야", "이에요", "예요",
    # 지시대명사 — 이전 주제를 가리키는 말이라 주제어가 아니다("그건 얼마야?")
    "그건", "그거", "그것", "이건", "이거", "이것", "저건", "저거", "저것",
    "거기", "여기", "그때", "그럼", "그러면",
)
# 서술어(동사·형용사) 어미 — 주제어가 아니므로 제외한다.
# 예: '내야해'(언제까지 내야해?)를 주제어로 오인하면 정상적인 맥락 보충까지 폐기된다.
_PREDICATE_SUFFIXES = ("해", "해요", "야해", "줘", "세요", "나요", "어요", "아요", "야", "다")
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def _distinctive_terms(question: str) -> list[str]:
    """질문에서 '주제를 식별하는' 토큰만 추출 (일반어·서술어 제외).

    비어 있으면 = 주제어 없는 모호한 후속 질문("기간은?") → 이전 맥락 보충이 정상이다.
    (애매하면 비우는 쪽이 안전 — 검사가 skip되어 재작성을 막지 않는다)"""
    terms = []
    for tok in _TOKEN_RE.findall(question or ""):
        if len(tok) < 2:
            continue
        if any(tok.startswith(g) for g in _GENERIC_TERMS):
            continue
        if any(tok.endswith(s) for s in _PREDICATE_SUFFIXES):
            continue
        terms.append(tok)
    return terms


def _keeps_topic(question: str, rewritten: str) -> bool:
    """재작성이 현재 질문의 주제어를 하나라도 유지하는지.

    프롬프트에 '현재 질문에 뚜렷한 주제어가 있으면 이전 질문을 무시하라'는 규칙이 있지만
    8B가 자주 어겨 이전 주제로 통째로 갈아탄다(실측: '휴학 신청 방법'→'공결 신청 방법',
    '학칙 알려줘'→'수강신청 방법'). 임베딩 드리프트 가드는 기준문이 '이전+현재'라
    이 경우를 못 잡으므로, 주제어 유지 여부를 코드로 확정 검사한다."""
    terms = _distinctive_terms(question)
    if not terms:
        return True                      # 모호한 후속 질문 → 검사 skip
    rw = (rewritten or "").replace(" ", "")
    return any(t in rw for t in terms)


def _clean_rewrite_output(raw: str | None) -> str:
    """LLM 재작성 출력 정리.
    - 빈/None 출력 안전 처리 (빈 문자열 반환)
    - 프롬프트 형식 에코 제거: LLM이 '… → 결과' 나 '이전 질문:… / 현재 질문:… → 결과'
      처럼 템플릿을 그대로 뱉는 경우 '→' 뒤(실제 결과)만 취한다.
    - 남은 '이전 질문:/현재 질문:/입력:/출력:' 접두 제거."""
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    text = lines[0]
    for arrow in ("→", "->"):                 # 프롬프트 화살표 에코 → 뒤만
        if arrow in text:
            text = text.split(arrow)[-1].strip()
    for pref in ("이전 질문:", "현재 질문:", "입력:", "출력:"):
        if text.startswith(pref):
            text = text.split(":", 1)[1].strip()
    return text.strip()


async def _rewrite_query(question: str, prev_question: str | None = None) -> str:
    """구어체 질문을 검색용 공식 용어로 변환.

    prev_question이 있으면(topic 유지된 후속 질문) 이전 질문의 주제어를 보충해
    재작성한다 — "기간은 얼마나 돼?"가 엉뚱한 검색어로 변환되는 것을 방지."""
    if prev_question:
        prompt = QUERY_REWRITE_WITH_CONTEXT_PROMPT.format(
            prev_question=prev_question, question=question
        )
    else:
        prompt = QUERY_REWRITE_PROMPT.format(question=question)
    rewritten = await llm_service.answer(
        prompt,
        max_tokens=64,
        system_prompt=KEYWORD_EXTRACTION_SYSTEM_PROMPT,
        temperature=0.0,   # 결정론적 출력으로 창의적 변형(환각) 억제
    )
    rewritten = _clean_rewrite_output(rewritten)   # 빈출력·프롬프트 형식 에코 안전 정리
    # 빈 출력이거나 원본과 동일 → 원본 사용
    if not rewritten or rewritten == question:
        print(f"[RAG_GENERAL] 질문 재작성 실패/빈출력 → 원본 사용: '{question}'")
        return question
    # 주제어 가드: 현재 질문에 뚜렷한 주제어가 있는데 재작성이 그걸 잃었으면(= 이전 주제로
    # 갈아탄 것) 원본 사용. 아래 드리프트 가드는 기준문에 이전 질문이 섞여 있어 이 경우를
    # 못 잡으므로, 그보다 먼저 확정적으로 차단한다.
    if not _keeps_topic(question, rewritten):
        print(f"[RAG_GENERAL] 재작성이 주제어 이탈 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question

    # 드리프트 가드: 재작성이 원문과 의미가 너무 멀어지면(예: 공결→전과) 원본 사용
    # 맥락 통합 시엔 주제어가 이전 질문에서 오므로 이전+현재를 합친 텍스트와 비교
    drift_ref = f"{prev_question} {question}" if prev_question else question
    if await _is_semantic_drift(drift_ref, rewritten):
        print(f"[RAG_GENERAL] 재작성 드리프트 감지 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question
    print(f"[RAG_GENERAL] 질문 재작성: '{question}' → '{rewritten}'"
          + (f" (이전 질문 맥락 통합: '{prev_question}')" if prev_question else ""))
    return rewritten


def _search_rag(search_query: str, original_question: str, topic: str | None) -> tuple[str, dict]:
    """Qdrant 검색. topic이 None이면 전체 검색."""
    try:
        print(
            f"[RAG_GENERAL] 선택된 topic: "
            f"{topic if topic else '전체 검색(None)'}"
        )

        context, results = rag_service.search_context_with_results(
            question=search_query,
            topic=topic,
            original_question=original_question,
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
    prev_question: str | None = None,
    search_query: str | None = None,
) -> tuple[str, dict]:
    """RAG 검색 후 LLM 답변 생성.

    topic: agent_graph에서 DB 라우팅으로 결정된 topic_name.
           None이면 전체 검색 (TopicRouter 미분류 — 분류 문장 보강 필요).
    prev_question: topic이 유지된 후속 질문일 때만 전달 — rewrite에 맥락 통합.
    """
    print("[RAG_GENERAL] RAG 검색 시작")

    effective_topic = topic
    if effective_topic is None:
        print("[RAG_GENERAL] ⚠️  TopicRouter 분류 실패 — topic=None, 전체 검색. 해당 질문의 분류 문장을 추가하세요.")
        print(f"[RAG_GENERAL] ⚠️  미분류 질문: {question}")

    # search_query가 주어지면(agent_graph의 rewrite 노드가 후속질문을 이미 재작성) 재사용,
    # 없으면(1차 질문) 여기서 구어체→키워드 재작성. (이중 rewrite / 이중 LLM 호출 방지)
    hoisted = search_query is not None
    if not hoisted:
        try:
            search_query = await _rewrite_query(question, prev_question=prev_question)
        except Exception as e:
            print(f"[RAG_GENERAL] rewrite 실패(원본 사용): {e}")
            search_query = question

    # 리랭킹 질문: 후속질문 원본은 맥락 없는 파편("기간은?")이라 리랭커 점수가 폭락한다.
    # → 후속(hoisted)은 재작성 쿼리("휴학 기간")로 리랭킹하고, 1차 질문은 기존대로 구어체 원본으로.
    rerank_question = search_query if hoisted else question

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        search_query,
        rerank_question,
        effective_topic,
    )

    # 파인튜닝 데이터용: 실제로 재작성된 경우에만 기록 (원본과 같으면 no-op이므로 None)
    metadata["rewritten_query"] = search_query if search_query != question else None

    # 검색 결과가 없으면 LLM 호출 스킵 — 근거 없는 답변(환각) 생성 방지
    if not context:
        print("[RAG_GENERAL] ⚠️ 검색 결과 0건 → LLM 호출 스킵, 안내 응답 반환")
        return (
            "죄송해요, 해당 내용에 대한 자료를 찾지 못했어요. "
            "조금 더 구체적으로 질문해 주시거나, "
            "학교 공식 홈페이지(wsu.ac.kr) 또는 담당 부서에 문의해 주세요.",
            metadata,
        )

    # LLM에는 이전 대화 맥락(이전 주제 힌트)이 포함된 질문 전달
    llm_question = context_question if context_question is not None else question

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    # 클럽 판정은 "현재 질문" 기준 — llm_question은 이전 주제 프리픽스를 포함하므로
    # 이전 질문에 "동아리"가 있었다고 현재 질문이 클럽 질문이 되는 오탐을 방지한다.
    is_club = "동아리" in question and effective_topic == "student_support"
    _LIST_KEYWORDS = {"목록", "종류", "어떤", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}
    is_club_list = is_club and any(kw in question for kw in _LIST_KEYWORDS)
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, topic={effective_topic}")

    from pathlib import Path
    matched_files: list[str] = []   # 임베딩 필터가 고른 관련 파일 (제안 확정용)

    if is_club_list:
        prompt = RAG_CLUB_LIST_PROMPT.format(context=context)
        answer = await llm_service.answer(prompt, max_tokens=2048)
    elif is_club:
        prompt = RAG_CLUB_DETAIL_PROMPT.format(context=context, question=llm_question)
        answer = await llm_service.answer(prompt, max_tokens=1024)
    else:
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files
        # 파일 매칭엔 '이전 주제:' 프리픽스가 낀 llm_question 대신 현재 질문 원본을 쓴다.
        # → 프리픽스 노이즈 제거 + "기간은?" 같은 파편 후속질문에 같은 파일 반복 제안 방지
        #   (현재 질문 자체가 그 주제(휴학 등)를 담고 있을 때만 유사도가 올라 제안됨).
        matched_files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get(effective_topic, [])
        )
        files_list = "\n".join(f"- {Path(f).stem}" for f in matched_files) if matched_files else "없음"
        prompt = RAG_GENERAL_PROMPT.format(context=context, question=llm_question, files_list=files_list)
        answer = await llm_service.answer(prompt)

    # 모델이 프롬프트 레이블을 이어서 출력하는 경우 가장 앞에 나온 위치에서 잘라내기
    _STOP_MARKERS = ["[참고 문서]", "[사용자 질문]", "[답변]", "[이전 질문]", "[이전 답변]", "[다운로드 가능 파일 목록]"]
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

    # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정한다.
    # 작은 로컬 LLM이 <FILES> 태그를 불안정하게 누락해 관련 파일을 못 주던 문제 →
    # 이미 검증된 임베딩 유사도 판단을 신뢰하고, LLM이 뽑은 태그는 화면에서 제거만 한다.
    import re
    match = re.search(r'<FILES>(.*?)</FILES>', answer)
    if match:
        answer = (answer[:match.start()] + answer[match.end():]).strip()
    if matched_files:
        metadata["files_to_offer"] = [Path(f).stem for f in matched_files]

    return answer, metadata


async def answer_rag_general_question(question: str, topic: str | None = None) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question, topic=topic)
    return answer
