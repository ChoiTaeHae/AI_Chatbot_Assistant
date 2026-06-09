import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

LEAVE_KNOWLEDGE = """
[우송대학교 휴학 안내]

신청순서: 대학정보시스템 로그인(wsinfo.wsu.ac.kr) -> 학적변동 -> 휴학신청

휴학 종류: 군휴학, 일반휴학연장, 군휴학변경, 출산및육아휴학, 창업휴학

군휴학 신청: 휴학종류선택 -> 군별/부사관여부 선택 -> 입영일자 선택 -> 주의사항확인 -> 입영통지서 업로드 -> 신청

주의사항: 일반휴학/일반휴학연장은 온라인 신청 불가, 학과사무실 상담 필요
"""

MAX_CONTEXT_LENGTH = 2000


def _search_rag(question: str) -> str:
    """RAG 검색 (동기, 별도 스레드에서 실행)"""
    try:
        context = rag_service.search_context(question, topic="leave")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return LEAVE_KNOWLEDGE


async def answer_leave_question(question: str) -> str:
    print("[LEAVE] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    # RAG는 별도 스레드에서 실행 (LLM과 충돌 방지)
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[LEAVE] RAG 검색 완료, LLM 호출")
    prompt = f"[휴학 안내]\n{context}\n\n질문: {question}\n답변:"
    return await chat_service.answer(prompt)
