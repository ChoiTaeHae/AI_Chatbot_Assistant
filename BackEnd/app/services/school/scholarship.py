import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.DB_Table import Scholarship, ScholarshipApp
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

MAX_CONTEXT_LENGTH = 2000

_PERSONAL_KEYWORDS = ["내가", "나는", "나", "내", "제가", "저는", "저", "제", "받을 수 있", "받을수있", "해당되"]

SCHOLARSHIP_FALLBACK = """
[우송대학교 장학금 안내]
장학금 관련 정보는 학교 공식 홈페이지(wsu.ac.kr) 장학금 안내 페이지를 참고하시거나,
학생처 장학팀에 문의하시기 바랍니다.
국가장학금은 한국장학재단(kosaf.go.kr)에서 신청 가능합니다.
"""


def _parse_gpa(text: str) -> float | None:
    """텍스트에서 GPA 추출 (예: '학점 3.5', '평점 4.0')"""
    match = re.search(r'(?:학점|평점|gpa|GPA)[\s:]*([0-9]+(?:\.[0-9]+)?)', text)
    if match:
        return float(match.group(1))
    match = re.search(r'\b([0-9]\.[0-9]+)(?:\s*점)?\b', text)
    if match:
        return float(match.group(1))
    return None


def _parse_income(text: str) -> int | None:
    """텍스트에서 소득분위 추출 (예: '3분위', '소득분위 5')"""
    match = re.search(r'(?:소득분위|소득구간|분위|구간)[\s:]*([0-9]+)', text)
    if match:
        return int(match.group(1))
    match = re.search(r'([0-9]+)\s*(?:분위|구간)', text)
    if match:
        return int(match.group(1))
    return None


def _search_rag(question: str) -> str:
    try:
        context = rag_service.search_context(question, topic="scholarship")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return SCHOLARSHIP_FALLBACK


async def _get_eligible_scholarships(db: AsyncSession, gpa: float, income_level: int) -> list:
    result = await db.execute(
        select(Scholarship).where(
            Scholarship.min_gpa <= gpa,
            Scholarship.income_level >= income_level
        )
    )
    return result.scalars().all()


async def _get_application_history(db: AsyncSession, student_id: int) -> list:
    result = await db.execute(
        select(ScholarshipApp).where(ScholarshipApp.student_id == student_id)
    )
    return result.scalars().all()


def _build_scholarship_context(scholarships: list, history: list) -> str:
    if not scholarships:
        return "조건에 맞는 장학금이 없습니다."

    applied_ids = {app.scholarship_id for app in history}
    lines = ["[조건에 맞는 장학금 목록]"]
    for s in scholarships:
        status = " (이미 신청함)" if s.id in applied_ids else ""
        lines.append(
            f"- {s.name} ({s.type}): 최소 평점 {s.min_gpa}, "
            f"소득분위 {s.income_level}분위 이하{status}"
        )
    return "\n".join(lines)


async def answer_scholarship_question(question: str, student_id: int = 1, db: AsyncSession = None) -> str:
    is_personal = any(kw in question for kw in _PERSONAL_KEYWORDS)

    if is_personal and db is not None:
        gpa = _parse_gpa(question)
        income = _parse_income(question)

        if gpa is None or income is None:
            missing = []
            if gpa is None: missing.append("학점(예: 학점 3.5)")
            if income is None: missing.append("소득분위(예: 3분위)")
            return (
                f"개인 장학금 조회를 위해 {' 와 '.join(missing)}을 알려주세요.\n"
                f"예) '학점 3.5이고 소득분위 3분위인데 받을 수 있는 장학금 있어?'"
            )

        print(f"[SCHOLARSHIP] DB 조회: GPA={gpa}, 소득분위={income}")
        scholarships = await _get_eligible_scholarships(db, gpa, income)
        history = await _get_application_history(db, student_id)
        context = _build_scholarship_context(scholarships, history)

        prompt = (
            f"{context}\n\n"
            f"위 내용을 바탕으로 학생의 장학금 수혜 가능 여부를 친절하게 안내해주세요.\n"
            f"질문: {question}\n답변:"
        )
        return await chat_service.answer(prompt)

    # 일반 장학금 정보 → RAG
    print("[SCHOLARSHIP] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[SCHOLARSHIP] RAG 검색 완료, LLM 호출")
    prompt = (
        f"[참고 문서]\n{context}\n\n"
        f"위 내용을 바탕으로 다음 장학금 관련 질문에 정확하게 답변해주세요.\n"
        f"문서에 없는 내용은 학생처 장학팀에 문의하도록 안내하세요.\n\n"
        f"질문: {question}\n답변:"
    )
    return await chat_service.answer(prompt)
