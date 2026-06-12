from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    pending_file: dict | None = None     # { topic, filename } 파일 제안에 대한 응답 시 프론트가 전달
    pending_context: dict | None = None  # { type: "scholarship" } 멀티턴 대화 상태


class ChatResponse(BaseModel):
    answer: str
    session_id: str | None = None
    file_offer: dict | None = None      # { topic, filename } AI가 파일을 제안할 때
    file_download: dict | None = None   # { topic, filename, url } 파일을 실제로 전송할 때
    map_card: dict | None = None        # { title, address, place_url, latitude, longitude } 캠퍼스 위치 검색 결과
    pending_context: dict | None = None # { type: "scholarship" } 멀티턴 대화 상태 유지용
