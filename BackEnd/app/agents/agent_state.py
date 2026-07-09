from typing import Any
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # 입력
    question: str
    student_id: int
    db: Any
    pending_file: dict | None
    pending_context: dict | None
    prev_context: dict | None        # 이전 대화 맥락 {"prev_question", "prev_answer", "prev_topic"}
    file_confirm: bool | None    # 프론트 예/아니오 버튼값 (True/False/None)

    # 분류
    intent: str | None       # campus / graduation / rag_general / general
    confidence: float        # 임베딩 유사도 점수
    search_query: str | None # 후속질문 rewrite 결과 (라우팅+검색에 사용, 1차 질문은 None)

    # 출력
    answer: str | None
    file_offer: dict | None
    file_download: dict | None
    map_card: dict | None
    next_pending_context: dict | None
    source: str | None
    source_file: str | None
    topic: str | None
    rewritten_query: str | None  # RAG 경로에서 생성된 검색용 재작성 질문 (파인튜닝 로깅용)
    done: bool               # pre_check에서 이미 처리 완료된 경우
