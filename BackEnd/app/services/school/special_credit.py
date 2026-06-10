import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

# TODO: RAG 검색 실패 시 사용할 기본 텍스트 - 추후 실제 내용으로 변경 필요
SPECIAL_CREDIT_KNOWLEDGE = """
[우송대학교 특별학점 안내]

특별학점이란: 정규 교과목 이외의 활동(자격증 취득, 비교과 활동 등)을 통해 학점으로 인정받는 제도

신청 가능 항목:
- 자격증 취득 (취득 시기 무관, 재학 중 신청 가능)
- 비교과 프로그램 이수
- 어학 성적 (공인 영어 성적 등)
- 봉사활동 시간

재수강과 특별학점: 재수강은 기존 이수 과목을 다시 수강하는 것으로, 특별학점 처리 대상이 아님

신청 기간: 매 학기 지정된 기간 내 신청 (정확한 기간은 학교 공지사항 확인)
승인 처리 기간: 신청 후 담당 부서 검토까지 통상 2~4주 소요
승인 후 효력: 승인된 학점은 해당 학기 학점에 반영되며, 수업 대체는 불가

문의처: 학사지원팀 또는 학과 사무실
"""

MAX_CONTEXT_LENGTH = 2000


def _search_rag(question: str) -> str:
    """RAG 검색 (동기, 별도 스레드에서 실행)"""
    try:
        context = rag_service.search_context(question, topic="special_credit")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return SPECIAL_CREDIT_KNOWLEDGE


async def answer_special_credit_question(question: str) -> str:
    print("[SPECIAL_CREDIT] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[SPECIAL_CREDIT] RAG 검색 완료, LLM 호출")
    prompt = (
        f"아래는 우송대학교 특별학점 관련 공식 안내 내용입니다.\n\n"
        f"{context}\n\n"
        f"위 내용을 참고하여 한국어로만 간결하게 답변하세요.\n"
        f"위 내용에 없는 정보는 '학사지원팀에 문의하시기 바랍니다'라고 답하세요.\n"
        f"질문: {question}"
    )
    return await chat_service.answer(prompt)
