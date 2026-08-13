"""학생 알림 스키마 — 내가 물었지만 답을 못 받은 질문에 답변이 등록됐을 때의 알림."""
from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    question: str          # 학생이 실제로 쳤던 원문 — 무엇에 대한 답인지 알아보게 한다
    answer: str            # 관리자가 등록한 FAQ 답변(조인해서 읽으므로 항상 최신)
    faq_id: int | None
    is_read: bool
    notified_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationCountResponse(BaseModel):
    unread: int
