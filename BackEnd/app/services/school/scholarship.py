import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

MAX_CONTEXT_LENGTH = 2000

SCHOLARSHIP_FALLBACK = """
[우송대학교 장학금 안내]
장학금 관련 정보는 학교 공식 홈페이지(wsu.ac.kr) 장학금 안내 페이지를 참고하시거나,
학생처 장학팀에 문의하시기 바랍니다.
국가장학금은 한국장학재단(kosaf.go.kr)에서 신청 가능합니다.
"""

def _search_rag(question: str) -> str:
    try:
        context = rag_service.search_context(question)
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return SCHOLARSHIP_FALLBACK


async def answer_scholarship_question(question: str) -> str:
    print("[SCHOLARSHIP] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[SCHOLARSHIP] RAG 검색 완료, LLM 호출")
    prompt = (
        f"[참고 문서]\n{context}\n\n"
        f"위 내용을 바탕으로 다음 장학금 관련 질문에 정확하게 답변해주세요.\n"
        f"신청 조건, 금액, 기간 등 구체적인 정보를 포함해 안내하고,\n"
        f"문서에 없는 내용은 학생처 장학팀에 문의하도록 안내하세요.\n\n"
        f"질문: {question}\n답변:"
    )
    return await chat_service.answer(prompt)
