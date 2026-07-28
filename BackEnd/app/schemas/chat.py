from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    session_id: int | None = None
    pending_file: dict | None = None     # { topic, filename } 파일 제안에 대한 응답 시 프론트가 전달
    pending_context: dict | None = None  # { type: "scholarship" } 멀티턴 대화 상태
    file_confirm: bool | None = None     # 프론트 예/아니오 버튼: True=예, False=아니오, None=일반 질문
    lang: str | None = None              # 프론트 UI 언어(ko/en/zh). 답변 후처리 번역 대상 판정용


class ChatResponse(BaseModel):
    answer: str
    session_id: int | None = None
    message_id: int | None = None       # chat_message.id (피드백 연결용)
    file_offer: dict | None = None      # { topic, files: [str] } AI가 파일 목록을 제안할 때
    file_download: dict | None = None   # { topic, filename, url } 파일을 실제로 전송할 때
    map_card: dict | None = None        # { title, address, place_url, latitude, longitude } 캠퍼스 위치 검색 결과
    schedule_card: dict | None = None   # { today, events: [{event, start_date, end_date}] } 학사일정 미니 달력
    dept_card: dict | None = None       # { kind, title, subtitle, items_label, items, homepage_url } 학과/학부/단과대 안내
    pending_context: dict | None = None # { type: "scholarship" } 멀티턴 대화 상태 유지용
    rewritten_query: str | None = None  # 검색용 재작성 질문 (개발용 rewrite 피드백 패널에서 사용, 변경 없으면 null)


class FeedbackRequest(BaseModel):
    message_id: int
    is_helpful: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = None


class RewriteFeedbackRequest(BaseModel):
    """개발용 rewrite 피드백 — 파인튜닝 라벨 수집."""
    message_id: int | None = None       # 연결할 (assistant) 메시지 id
    question: str                        # 원본 질문 (입력)
    model_rewrite: str | None = None     # 모델이 뱉은 rewrite
    prev_question: str | None = None     # 맥락모드면 이전 질문
    is_good: bool                        # rewrite가 적절했나
    corrected: str | None = None         # 나쁠 때 교정한 정답 rewrite
