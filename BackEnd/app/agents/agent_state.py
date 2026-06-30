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

    # 분류
    intent: str | None       # campus / graduation / rag_general / general
    confidence: float        # 임베딩 유사도 점수

    # 출력
    answer: str | None
    file_offer: dict | None
    file_download: dict | None
    map_card: dict | None
    next_pending_context: dict | None
    source: str | None
    source_file: str | None
    topic: str | None
    done: bool               # pre_check에서 이미 처리 완료된 경우
