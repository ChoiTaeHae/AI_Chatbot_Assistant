from pydantic import BaseModel
from typing import Optional


# ── 문서 관련 ──────────────────────────────────────────
class DocumentUploadResponse(BaseModel):
    success: bool
    source: str
    file_name: str
    chunks: int
    message: str


class DocumentListItem(BaseModel):
    source: str
    file_name: Optional[str] = None
    chunks: int
    topic: Optional[str] = None


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
    role: str
