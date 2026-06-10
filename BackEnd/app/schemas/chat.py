from pydantic import BaseModel
from typing import List, Optional


class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # 나중에 대화 기록용 (DB 연동 시 사용)
    student_no: Optional[str] = None   # 로그인한 사용자 학번
    pending_file: Optional[dict] = None  # 파일 제안에 답할 때 전달됨

class ChatResponse(BaseModel):
    answer: str
    session_id: Optional[str] = None
    file_offer: Optional[dict] = None      # { topic, filename } — "보내드릴까요?" 제안
    file_download: Optional[dict] = None   # { topic, filename, url } — 다운로드 링크
    map_card: Optional[dict] = None        # 캠퍼스 지도 카드