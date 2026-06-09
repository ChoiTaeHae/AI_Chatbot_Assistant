from pydantic import BaseModel
from typing import List, Optional

#첨부파일 규격 추가
class Attachment(BaseModel):
    file_name: str
    file_url: str
    file_type: str

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # 나중에 대화 기록용 (DB 연동 시 사용)
    student_no: Optional[str] = None   # 로그인한 사용자 학번

class ChatResponse(BaseModel):
    answer: str
    session_id: Optional[str] = None
    attachment: List[Attachment] = []  # 리스트 추가
