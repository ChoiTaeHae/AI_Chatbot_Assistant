import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service
from app.language import detect_language

ABSENCE_KNOWLEDGE = """
[우송대학교 공결(병결) 안내]

공결이란 : 학교가 인정하는 사유(군입대, 예비군/민방위, 학교 공식 행사 등)로 인한
결석을 출석으로 처리해주는 제도

신청 가능 사유:
- 예비군/민방위 훈련(훈련 확인서 필요)
- 군 입영 관련
- 학교 공식 행사 참가(대회, 봉사 등 학교 승인 활동)
- 교통사고, 입원, 질병으로 인한 당일 진료(관련 서류 필요)
- 재학 중 취업(재직증명서 및 건강보험가입(사실)확인서)

신청방법 : 사유 발생 후 서류 작성해서(확인서 필요) 각 학과의 학과사무실로 제출
제출 서류 : 훈련 확인서, 진단서 등 사유를 증명할 수 있는 공식 서류
신청 기한 : 사유 발생일로부터 1주일 이내(학과마다 다를 수 있음)

문의처 : 학과사무실
"""

MAX_CONTEXT_LENGTH = 2000

def _search_rag(question: str) -> str:
    try:
        context = rag_service.search_context(question, topic="absence")
        if context:
            return context[:MAX_CONTEXT_LENGTH]
    except Exception as e:
        print(f"[RAG] 검색 실패, 기본 텍스트 사용: {e}")
    return ABSENCE_KNOWLEDGE


async def answer_absence_question(question: str) -> str:
    print("[ABSENCE] RAG 검색 시작")
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(None, _search_rag, question)
    print("[ABSENCE] RAG 검색 완료, LLM 호출")

    lang = detect_language(question)

    if lang == 'en':
        lang_rule = "Respond in English"
    elif lang == 'zh':
        lang_rule = "请用中文回答。"
    else:
        lang_rule = "한국어로 간결하게 답변하세요."

    prompt = (
        f"아래는 우송대학교 공결(병결) 관련 공식 안내 내용입니다."
        f"{context}\n\n"
        f"위 내용을 참고하여 답변하세요. {lang_rule}\n"
        f"위 내용에 없는 정보는 각 학과의 학과사무실로 문의하시기 바랍니다."
        f"질문 : {question}"
    )
    return await chat_service.answer(prompt)