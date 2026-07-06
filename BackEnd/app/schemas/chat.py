from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    session_id: int | None = None
    pending_file: dict | None = None     # { topic, filename } 파일 제안에 대한 응답 시 프론트가 전달
    pending_context: dict | None = None  # { type: "scholarship" } 멀티턴 대화 상태
    file_confirm: bool | None = None     # 프론트 예/아니오 버튼: True=예, False=아니오, None=일반 질문


class ChatResponse(BaseModel):
    answer: str
    session_id: int | None = None
    message_id: int | None = None       # chat_message.id (피드백 연결용)
    file_offer: dict | None = None      # { topic, files: [str] } AI가 파일 목록을 제안할 때
    file_download: dict | None = None   # { topic, filename, url } 파일을 실제로 전송할 때
    map_card: dict | None = None        # { title, address, place_url, latitude, longitude } 캠퍼스 위치 검색 결과
    pending_context: dict | None = None # { type: "scholarship" } 멀티턴 대화 상태 유지용


class FeedbackRequest(BaseModel):
    message_id: int
    is_helpful: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = None
