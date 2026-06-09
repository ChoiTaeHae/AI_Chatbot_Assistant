import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service


#TODO: RAG 검색 실패 시 사용할 기본 텍스트 (OT 관련 정보) 추후 변경 필요
OT_KNOWLEDGE = """
[우송대학교 OT(오리엔테이션) 안내]

신입생 OT: 매년 2월 말 ~ 3월 초, 입학 전 신입생 대상으로 진행
학과 OT: 각 학과별로 개강 초 진행 (일정은 학과사무실 문의)

주요 내용:
- 학교 생활 안내 (수강신청, 학사일정, 장학금 등)
- 학과 교수님 및 선배와의 만남
- 교내 시설 안내

참석 방법: 학교 공지사항 또는 학과 공지를 통해 일정 확인 후 참석
문의처: 각 학과 사무실 또는 학생처
"""

MAX_CONTEXT_LENGTH = 2000


def _search_rag(question: str) -> str:
    """RAG 검색 (동기, 별도 스레드에서 실행)"""
    try:
        context = rag_service.search_context(question)
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return OT_KNOWLEDGE


async def answer_ot_question(question: str) -> str:
    print("[OT] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[OT] RAG 검색 완료, LLM 호출")
    prompt = (
        f"아래는 우송대학교 OT(오리엔테이션) 관련 공식 안내 내용입니다.\n\n"
        f"{context}\n\n"
        f"위 내용을 참고하여 한국어로만 간결하게 답변하세요.\n"
        f"위 내용에 없는 정보는 '확인이 필요합니다'라고 답하세요.\n"
        f"질문: {question}"
    )
    return await chat_service.answer(prompt)
