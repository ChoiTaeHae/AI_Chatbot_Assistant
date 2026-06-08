from app.services.chat_service import chat_service

async def answer_schedule_question(question: str) -> str:
    """학사일정 관련 질문을 LLM으로 처리"""
    # TODO: DB에 학사일정 테이블 추가되면 DB 조회로 교체
    prompt = f"""당신은 우송대학교 학사일정 안내 도우미입니다.
학사일정 관련 질문에 답변해주세요.
DB 연동 전이므로 일반적인 대학 학사일정 기준으로 안내하되,
정확한 일정은 학교 홈페이지(wsu.ac.kr) 또는 학사지원팀에 문의하도록 안내하세요.

질문: {question}
답변:"""
    return await chat_service.answer(prompt)
