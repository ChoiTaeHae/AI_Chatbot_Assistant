import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

MAX_CONTEXT_LENGTH = 2000

SCHEDULE_FALLBACK = """
[우송대학교 학사일정 안내]
정확한 학사일정은 학교 공식 홈페이지(wsu.ac.kr) 또는 학사지원팀에 문의하시기 바랍니다.
대학정보시스템(wsinfo.wsu.ac.kr)에서도 확인할 수 있습니다.
"""


def _search_rag(question: str) -> str:
    try:
        context = rag_service.search_context(question, topic="schedule")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return SCHEDULE_FALLBACK


async def answer_schedule_question(question: str) -> str:
    print("[SCHEDULE] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[SCHEDULE] RAG 검색 완료, LLM 호출")
    prompt = (
        f"[참고 문서]\n{context}\n\n"
        f"위 내용을 바탕으로 다음 질문에 정확하게 답변해주세요.\n"
        f"문서에 없는 내용은 학교 홈페이지(wsu.ac.kr) 또는 학사지원팀에 문의하도록 안내하세요.\n\n"
        f"질문: {question}\n답변:"
    )
    return await chat_service.answer(prompt)
