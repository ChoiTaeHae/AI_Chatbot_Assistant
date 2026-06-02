# from pydantic import BaseModel



class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None  # 나중에 대화 기록용 (DB 연동 시 사용)


class ChatResponse(BaseModel):
    answer: str
    session_id: str | None = None

