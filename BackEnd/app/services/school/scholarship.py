import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

MAX_CONTEXT_LENGTH = 2000

# 맞춤 조회 의도가 명확한 키워드 (단순 "나", "내" 같은 일반 대명사 제외)
_ELIGIBILITY_KEYWORDS = [
    "받을 수 있", "받을수있", "해당되", "해당하는지", "대상인지",
    "맞춤", "내가 받", "제가 받", "나 받", "저 받",
    "신청 가능", "신청가능", "자격 되", "자격이 되",
]

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


def _search_rag(question: str) -> str | None:
    """RAG 검색. 문서가 없으면 None 반환."""
    try:
        context = rag_service.search_context(question, topic="scholarship")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패: {e}")
    return None


async def _rag_and_llm(question: str, gpa: float, income: int) -> str:
    """RAG 검색 후 문서가 있으면 LLM 맞춤 답변, 없으면 안내 메시지 반환."""
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)

    if context is None:
        return (
            f"학점 {gpa}, 소득분위 {income}분위로 확인했지만,\n"
            f"현재 장학금 관련 문서가 등록되어 있지 않아 맞춤 조회가 어렵습니다.\n"
            f"학생처 장학팀(wsu.ac.kr)에 문의하시거나 한국장학재단(kosaf.go.kr)을 이용하세요."
        )

    prompt = (
        f"[장학금 안내 문서]\n{context}\n\n"
        f"[학생 조건]\n"
        f"- 학점(GPA): {gpa}\n"
        f"- 소득분위: {income}분위\n\n"
        f"위 장학금 안내 문서를 참고하여, 이 학생이 받을 수 있는 장학금을 알려주세요.\n"
        f"조건에 맞는 장학금이 없으면 없다고 답하세요.\n"
        f"문서에 없는 내용은 추측하지 마세요.\n"
        f"질문: {question}\n답변:"
    )
    return await chat_service.answer(prompt)


async def answer_scholarship_question(
    question: str,
    student_id: int = 1,
    db: AsyncSession = None,
    pending_context: dict | None = None,
) -> tuple[str, dict | None]:
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
            )

        else:
            # GPA + 소득분위 모두 수집 완료
            print(f"[SCHOLARSHIP] 멀티턴 완료: GPA={gpa}, 소득분위={income}")
            return await _rag_and_llm(question, gpa, income), None

    # 최초 진입: 맞춤 조회 의도인지 확인
    is_personal = any(kw in question for kw in _ELIGIBILITY_KEYWORDS)

    if is_personal:
        gpa = _parse_gpa(question)
        income = _parse_income(question)

        if gpa is not None and income is not None:
            # 한 번에 모두 입력된 경우
            print(f"[SCHOLARSHIP] 개인 조회: GPA={gpa}, 소득분위={income}")
            return await _rag_and_llm(question, gpa, income), None

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
        )

    # 일반 장학금 정보 → RAG
    print("[SCHOLARSHIP] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)

    if context is None:
        print("[SCHOLARSHIP] 문서 없음 → 안내 메시지 반환")
        return NO_DOCS_MESSAGE, None

    print("[SCHOLARSHIP] RAG 검색 완료, LLM 호출")
    prompt = (
        f"[참고 문서]\n{context}\n\n"
        f"위 내용을 바탕으로 다음 장학금 관련 질문에 정확하게 답변해주세요.\n"
        f"문서에 없는 내용은 학생처 장학팀에 문의하도록 안내하세요.\n\n"
        f"질문: {question}\n답변:"
    )
    return await chat_service.answer(prompt), None
