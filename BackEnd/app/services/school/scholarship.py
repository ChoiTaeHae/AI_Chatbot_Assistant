import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.prompts import SCHOLARSHIP_SYSTEM_PROMPT

MAX_CONTEXT_LENGTH = 1000

# 맞춤 조회 의도가 명확한 키워드 (단순 "나", "내" 같은 일반 대명사 제외)
_ELIGIBILITY_KEYWORDS = [
    "받을 수 있", "받을수있", "해당되", "해당하는지", "대상인지",
    "맞춤", "내가 받", "제가 받", "나 받", "저 받",
    "신청 가능", "신청가능", "자격 되", "자격이 되",
]

_PROMPT_RULES = (
    "[답변 규칙 - 반드시 준수]\n"
    "1. 위 문서에 이름이 명시된 장학금만 언급하세요. 문서에 없는 장학금 이름은 절대 만들지 마세요.\n"
    "2. 금액, 조건, 기준이 문서에 명확히 적혀 있을 때만 해당 내용을 답하세요.\n"
    "3. 문서에서 확인되지 않는 내용은 '문서에서 확인되지 않습니다'라고 하세요.\n"
    "4. 확실하지 않으면 학생처 장학팀(wsu.ac.kr) 문의를 안내하세요.\n"
)

NO_DOCS_MESSAGE = (
    "현재 장학금 관련 문서가 등록되어 있지 않습니다.\n"
    "자세한 내용은 학교 공식 홈페이지(wsu.ac.kr) 장학금 안내 페이지를 참고하시거나,\n"
    "학생처 장학팀에 문의하시기 바랍니다.\n"
    "국가장학금은 한국장학재단(kosaf.go.kr)에서 신청 가능합니다."
)


def _parse_gpa(text: str) -> float | None:
    match = re.search(r'(?:학점|평점|gpa|GPA)[\s:]*([0-9]+(?:\.[0-9]+)?)', text)
    if match:
        return float(match.group(1))
    match = re.search(r'\b([0-9]\.[0-9]+)(?:\s*점)?\b', text)
    if match:
        return float(match.group(1))
    return None


def _parse_income(text: str) -> int | None:
    match = re.search(r'(?:소득분위|소득구간|분위|구간)[\s:]*([0-9]+)', text)
    if match:
        return int(match.group(1))
    match = re.search(r'([0-9]+)\s*(?:분위|구간)', text)
    if match:
        return int(match.group(1))
    return None


def _search_rag(question: str) -> tuple[str, dict] | None:
    """RAG 검색. 문서가 없으면 None 반환."""
    try:
        context, results = rag_service.search_context_with_results(question, topic="scholarship")
        if context:
            return context[:MAX_CONTEXT_LENGTH], rag_service.primary_metadata(results, topic="scholarship")
    except Exception as e:
        print(f"[RAG] 검색 실패: {e}")
    return None


async def _rag_and_llm(question: str, gpa: float, income: int) -> tuple[str, dict]:
    """RAG 검색 후 문서가 있으면 LLM 맞춤 답변, 없으면 안내 메시지 반환."""
    loop = asyncio.get_event_loop()
    search_data = await loop.run_in_executor(None, _search_rag, question)

    if search_data is None:
        return (
            f"학점 {gpa}, 소득분위 {income}분위로 확인했지만,\n"
            f"현재 장학금 관련 문서가 등록되어 있지 않아 맞춤 조회가 어렵습니다.\n"
            f"학생처 장학팀(wsu.ac.kr)에 문의하시거나 한국장학재단(kosaf.go.kr)을 이용하세요.",
            {"source": None, "source_file": None, "topic": "scholarship"},
        )

    context, metadata = search_data
    prompt = (
        f"[장학금 안내 문서]\n{context}\n\n"
        f"[학생 조건]\n"
        f"- 학점(GPA): {gpa}\n"
        f"- 소득분위: {income}분위\n\n"
        f"{_PROMPT_RULES}\n"
        f"위 규칙을 지켜 이 학생이 받을 수 있는 장학금을 알려주세요.\n"
        f"질문: {question}\n답변:"
    )
    return await llm_service.answer(prompt, system_prompt=SCHOLARSHIP_SYSTEM_PROMPT), metadata


async def answer_scholarship_question(
    question: str,
    student_id: int = 1,
    db: AsyncSession = None,
    pending_context: dict | None = None,
) -> tuple[str, dict | None, dict]:
    """
    반환: (answer, next_pending_context)
    - next_pending_context가 None이면 대화 종료
    - next_pending_context가 { type: "scholarship", gpa: ..., income: ... } 이면 계속 수집 중
    """

    # 멀티턴: 이전에 GPA/소득 수집 중이었던 경우
    if pending_context and pending_context.get("type") == "scholarship":
        saved_gpa = pending_context.get("gpa")
        saved_income = pending_context.get("income")

        gpa = saved_gpa or _parse_gpa(question)
        income = saved_income or _parse_income(question)

        # 값이 하나도 파싱 안 되면 새 질문으로 간주 → 일반 RAG로 리셋
        if gpa is None and income is None and saved_gpa is None and saved_income is None:
            pass  # 아래 일반 로직으로 이어짐

        elif gpa is None or income is None:
            missing = []
            if gpa is None:
                missing.append("학점(예: 학점 3.5)")
            if income is None:
                missing.append("소득분위(예: 3분위)")
            return (
                f"{' 와 '.join(missing)}을 알려주세요.",
                {"type": "scholarship", "gpa": gpa, "income": income},
                {"source": None, "source_file": None, "topic": "scholarship"},
            )

        else:
            # GPA + 소득분위 모두 수집 완료
            print(f"[SCHOLARSHIP] 멀티턴 완료: GPA={gpa}, 소득분위={income}")
            answer, metadata = await _rag_and_llm(question, gpa, income)
            return answer, None, metadata

    # 최초 진입: 맞춤 조회 의도인지 확인
    is_personal = any(kw in question for kw in _ELIGIBILITY_KEYWORDS)

    if is_personal:
        gpa = _parse_gpa(question)
        income = _parse_income(question)

        if gpa is not None and income is not None:
            # 한 번에 모두 입력된 경우
            print(f"[SCHOLARSHIP] 개인 조회: GPA={gpa}, 소득분위={income}")
            answer, metadata = await _rag_and_llm(question, gpa, income)
            return answer, None, metadata

        # GPA나 소득분위 없음 → 멀티턴 시작
        missing = []
        if gpa is None:
            missing.append("학점(예: 학점 3.5)")
        if income is None:
            missing.append("소득분위(예: 3분위)")
        return (
            f"개인 장학금 조회를 위해 {' 와 '.join(missing)}을 알려주세요.\n"
            f"예) '학점 3.5이고 소득분위 3분위인데 받을 수 있는 장학금 있어?'",
            {"type": "scholarship", "gpa": gpa, "income": income},
            {"source": None, "source_file": None, "topic": "scholarship"},
        )

    from app.prompts import RAG_SCHOLARSHIP_PROMPT

    # 일반 장학금 정보 → RAG
    print("[SCHOLARSHIP] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    search_data = await loop.run_in_executor(None, _search_rag, question)

    if search_data is None:
        print("[SCHOLARSHIP] 문서 없음 → 안내 메시지 반환")
        return NO_DOCS_MESSAGE, None, {"source": None, "source_file": None, "topic": "scholarship"}

    context, metadata = search_data
    print("[SCHOLARSHIP] RAG 검색 완료, LLM 호출")

    from app.services.file_service import AVAILABLE_FILES
    from pathlib import Path
    files = AVAILABLE_FILES.get("scholarship", [])
    files_list = "\n".join(f"- {Path(f).stem}" for f in files) if files else "없음"

    prompt = RAG_SCHOLARSHIP_PROMPT.format(context=context, question=question, files_list=files_list)
    answer = await llm_service.answer(prompt, system_prompt=SCHOLARSHIP_SYSTEM_PROMPT)

    import re
    match = re.search(r'<FILES>(.*?)</FILES>', answer)
    if match:
        files_str = match.group(1)
        metadata["files_to_offer"] = [f.strip() for f in files_str.split(',') if f.strip()]
        answer = answer[:match.start()] + answer[match.end():]
        answer = answer.strip()

    return answer, None, metadata
