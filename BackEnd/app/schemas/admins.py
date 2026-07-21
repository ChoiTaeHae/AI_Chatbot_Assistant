from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime
from datetime import date

# ── 문서 관련 ──────────────────────────────────────────
class DocumentUploadResponse(BaseModel):
    success: bool
    source: str
    file_name: str
    chunks: int
    message: str

class DocumentUploadRequest(BaseModel):
    source: str
    topic: Optional[str] = None
    doc_date: Optional[date] = None  

class DocumentListItem(BaseModel):
    source: str
    file_name: Optional[str] = None
    chunks: int
    topic: Optional[str] = None
    doc_date: Optional[str] = None 


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int


class DocumentDeleteResponse(BaseModel):
    success: bool
    source: str
    message: str


# ── 대시보드 관련 ───────────────────────────────────────
class DashboardResponse(BaseModel):
    total_documents: int
    total_chunks: int
    model_status: str
    dev_mode: bool
    model_path: str


# ── 사용 통계 관련 ──────────────────────────────────────
class StatsResponse(BaseModel):
    total_students: int
    total_departments: int
    total_courses: int
    total_admins: int


class DailyCount(BaseModel):
    date: str   # "MM-DD"
    count: int


class TopicCount(BaseModel):
    intent: str
    count: int
    label: str


class ChatStatsResponse(BaseModel):
    total_chats: int
    today_chats: int
    active_students_7d: int
    daily_counts: list[DailyCount]     # 최근 7일 일별 질문 수
    topic_counts: list[TopicCount]     # 주제별 질문 분포


# ── 서비스 설정 관련 ────────────────────────────────────
class SettingsResponse(BaseModel):
    dev_mode: bool
    model_path: str
    device: str
    embedding_model: str
    embedding_device: str
    qdrant_collection: str
    rag_top_k: int


# ── 보안/권한 관련 ──────────────────────────────────────
class UserItem(BaseModel):
    id: int
    student_no: str
    name: str
    role: str
    department: str


class UserListResponse(BaseModel):
    users: list[UserItem]
    total: int


class RoleUpdate(BaseModel):
    role: Literal["student", "admin"]


# ── 채팅 내역 관련 ──────────────────────────────────────
class FeedbackItem(BaseModel):
    id: int
    is_helpful: bool
    rating: Optional[int] = None
    comment: Optional[str] = None
    created_at: Optional[datetime] = None


class AdminFeedbackRequest(BaseModel):
    is_helpful: bool
    rating: Optional[int] = None
    comment: Optional[str] = None


class ChatSessionItem(BaseModel):
    id: int
    student_name: Optional[str] = None
    student_no: Optional[str] = None
    intent: Optional[str] = None
    message_count: int
    first_message: Optional[str] = None
    started_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionItem]
    total: int


class ChatMessageItem(BaseModel):
    id: int
    role: str
    content: str
    intent: Optional[str] = None
    topic: Optional[str] = None
    source: Optional[str] = None
    source_file: Optional[str] = None
    created_at: Optional[datetime] = None
    feedback: Optional[FeedbackItem] = None


class ChatSessionDetailResponse(BaseModel):
    session_id: int
    student_name: Optional[str] = None
    student_no: Optional[str] = None
    messages: list[ChatMessageItem]


# ── Topic 관리 관련 ──────────────────────────────────────
class TopicItem(BaseModel):
    id: int
    name: str
    label: str
    handler_type: str
    sentences: list[str]
    description: Optional[str] = None
    is_system: bool
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TopicCreateRequest(BaseModel):
    name: str
    label: str
    handler_type: str = "rag"
    sentences: list[str] = []
    description: Optional[str] = None


class TopicUpdateRequest(BaseModel):
    label: Optional[str] = None
    sentences: Optional[list[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ── 학사일정 관리 관련 ──────────────────────────────────────
class ScheduleItem(BaseModel):
    id: int
    academic_year: int
    track: str
    event: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    raw: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleCreateRequest(BaseModel):
    academic_year: int
    track: str = "학부"
    event: str
    start_date: date
    end_date: Optional[date] = None   # 미지정이면 하루짜리(start=end)


class ScheduleUpdateRequest(BaseModel):
    academic_year: Optional[int] = None
    track: Optional[str] = None
    event: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ScheduleGateConfig(BaseModel):
    # 학사일정 날짜-게이트 키워드 (어드민 편집)
    date_intent: list[str] = []       # "언제", "며칠", "언제까지" 등
    event_keywords: list[str] = []    # "수강신청", "성적", "휴학" 등
