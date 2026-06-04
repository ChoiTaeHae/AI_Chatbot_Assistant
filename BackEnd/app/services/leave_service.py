from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

# ============================================================
# 우송대학교 휴학 관련 문서 컨텍스트
# 현재: RAG 검색 결과를 우선 사용하고, 인덱싱 전에는 임시 컨텍스트 사용
# ============================================================

LEAVE_KNOWLEDGE = """
[우송대학교 휴학 안내]

■ 신청 순서
1. 대학정보시스템 로그인 (https://wsinfo.wsu.ac.kr)
2. 상단 학적 메뉴 → 학적변동 선택
3. 휴학신청 메뉴 선택

■ 휴학 종류
- 군휴학
- 일반휴학연장
- 군휴학변경
- 출산 및 육아휴학
- 창업휴학

■ 군휴학 신청 방법
1. 휴학종류에서 군휴학 선택
2. 부사관 여부 및 군별 선택
3. 입영일자 선택
4. 주의사항 확인 체크
5. 휴학사유 선택 후 입영통지서(PDF, JPG) 파일 업로드
6. 신청 버튼 클릭

■ 군휴학 변경 신청 방법
1. 휴학종류에서 군휴학변경 선택
2. 부사관 여부 및 군별 선택
3. 입영일자 선택
4. 주의사항 확인 체크
5. 입영영장(PDF, JPG) 파일 업로드
6. 휴학신청 버튼 클릭

■ 주의사항
- 일반휴학 및 일반휴학연장은 온라인 신청 불가 → 학과사무실 상담 후 신청
- 군휴학 변경은 온라인으로 신청 가능
- 전과신청 이후에는 전과 신청불가
- 전과를 신청한 학생은 전입학부(과)의 교육과정에 따라 전입학과와의 교류기준 학점 필수 이수
"""


def get_context() -> str:
    """휴학 관련 컨텍스트 반환."""
    try:
        context = rag_service.search_context("우송대학교 휴학 군휴학 일반휴학 휴학신청")
        if context:
            return context
    except Exception as e:
        print(f"[RAG] 휴학 컨텍스트 검색 실패, 임시 컨텍스트 사용: {e}")

    return LEAVE_KNOWLEDGE


async def answer_leave_question(question: str) -> str:
    """휴학 관련 질문에 컨텍스트를 포함해서 LLM에 전달"""
    context = get_context()
    prompt = f"""다음은 우송대학교 휴학 관련 공식 안내 내용입니다:

{context}

위 내용을 바탕으로 다음 질문에 답변해주세요:
{question}

안내 내용에 없는 사항은 학과사무실 또는 학생처에 문의하도록 안내해주세요."""

    return await chat_service.answer(prompt)
