import asyncio
from pathlib import Path

from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

RAG_GENERAL_TOPIC = "rag_general"
RAG_GENERAL_SOURCE = "rag_general_knowledge"

RAG_GENERAL_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "rag_general_knowledge.md"
)

MAX_CONTEXT_LENGTH = 1000


def ensure_rag_general_knowledge() -> None:
    """서버 시작 시 기본 학교생활 지식 적재"""
    if not RAG_GENERAL_KNOWLEDGE_PATH.exists():
        print(f"[RAG_GENERAL] 기본 지식 파일 없음: {RAG_GENERAL_KNOWLEDGE_PATH}")
        return

    try:
        sources = rag_service.vector_store.list_sources()

        if any(item.get("source") == RAG_GENERAL_SOURCE for item in sources):
            print("[RAG_GENERAL] 기본 지식 이미 적재됨")
            return

        chunks = rag_service.ingest_document(
            RAG_GENERAL_KNOWLEDGE_PATH,
            source=RAG_GENERAL_SOURCE,
            topic=RAG_GENERAL_TOPIC,
        )

        print(f"[RAG_GENERAL] 기본 지식 적재 완료: {chunks} chunks")

    except Exception as e:
        print(f"[RAG_GENERAL] 기본 지식 적재 실패 (무시): {e}")


def _fallback_context() -> str:
    try:
        return RAG_GENERAL_KNOWLEDGE_PATH.read_text(
            encoding="utf-8"
        )[:MAX_CONTEXT_LENGTH]

    except Exception:
        return (
            "학교생활 관련 정보는 우송대학교 공식 홈페이지, "
            "대학정보시스템, 학과사무실 또는 담당 부서를 확인해주세요."
        )


def _search_rag(question: str) -> str:
    try:
        context = rag_service.search_context(
            question,
            # topic=RAG_GENERAL_TOPIC,
        )

        print("\n========== RAG CONTEXT ==========")
        print(context)
        print("=================================\n")

        if context:
            return context[:MAX_CONTEXT_LENGTH]

    except Exception as e:
        print(f"[RAG_GENERAL] 검색 실패, 기본 텍스트 사용: {e}")

    return _fallback_context()


async def answer_rag_general_question(question: str) -> str:
    print("[RAG_GENERAL] RAG 검색 시작")

    loop = asyncio.get_event_loop()

    context = await loop.run_in_executor(
        None,
        _search_rag,
        question,
    )

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    prompt = f"""

규칙:
- 사용자의 질문에 바로 답변한다.
- 인사말을 하지 않는다.
- 자기소개를 하지 않는다.
- "궁금한 점이 있으신가요?"와 같은 추가 질문을 하지 않는다.
- 참고 문서에 있는 내용만 근거로 답변한다.
- 문서에 없는 일정, 기간, 비용, 운영 여부는 추측하지 않는다.
- 필요한 경우 공식 홈페이지, 대학정보시스템, 학과사무실 또는 담당 부서 확인을 안내한다.
- 답변은 간결하고 자연스러운 한국어로 작성한다.

[참고 문서]
{context}

[사용자 질문]
{question}

[답변]
"""

    return await chat_service.answer(prompt)