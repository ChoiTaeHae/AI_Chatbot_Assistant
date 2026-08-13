from pydantic import BaseModel, Field
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
    # 수정 폼 초기값 채우기용 — 목록 한 번으로 폼을 열 수 있게 함께 내려준다
    url: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int


class DocumentUpdateRequest(BaseModel):
    """문서 메타데이터 수정 — 보낸 필드만 갱신한다(exclude_unset).

    본문(text)·벡터는 건드리지 않으므로 재임베딩이 없고, 손으로 정리해 둔 청크도 보존된다.
    문서명(source)과 파일 내용은 이 경로로 바꿀 수 없다(문서명은 point id를 결정하므로
    전 청크 재적재가 필요 — 필요해지면 별도 엔드포인트로 다룬다).
    """
    topic: Optional[str] = None
    doc_date: Optional[str] = None
    url: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class DocumentUpdateResponse(BaseModel):
    success: bool
    source: str
    updated_chunks: int
    message: str


class ChunkItem(BaseModel):
    """저장된 청크 하나. point_id는 Qdrant 포인트 식별자로, 화면 key와 수정 대상 지정에 쓴다."""
    point_id: str
    chunk_index: int
    text: str
    chars: int
    path: Optional[str] = None
    chapter: Optional[str] = None
    article: Optional[str] = None


class ChunkListResponse(BaseModel):
    source: str
    chunks: list[ChunkItem]
    total: int


class ChunkUpdateRequest(BaseModel):
    """청크 본문 수정 — 저장하면 이 청크 하나만 다시 임베딩된다.

    본문이 바뀌면 벡터도 같이 바뀌어야 검색이 맞는다(메타데이터 수정과 다른 점).
    나머지 청크는 손대지 않으므로 문서 재업로드처럼 전체가 다시 쪼개지지 않는다.
    """
    text: str


class ChunkUpdateResponse(BaseModel):
    success: bool
    source: str
    chunk_index: int
    chars: int
    message: str


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
    llm_provider: str        # local(Bllossom) | vertex(Gemini) — 지금 답변을 만드는 쪽
    llm_model: str           # provider에 맞는 실제 모델(경로 또는 모델명)
    model_path: str          # 로컬 GGUF 경로 (provider=vertex여도 참고용으로 유지)
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


# ── FAQ 관리 관련 ──────────────────────────────────────────
# FAQ는 '검수된 답변 1개 + 매칭용 질문 변형 N개' 구조다(faq / faq_question).
# 질문 변형은 개별 CRUD 대신 목록 전체를 교체한다 — 한 FAQ의 변형이 많아야 십수 개라
# 부분 갱신의 이점이 없고, 화면에서도 텍스트 여러 줄을 한 번에 저장하는 편이 자연스럽다.
class FaqQuestionItem(BaseModel):
    id: int
    text: str
    enabled: bool

    class Config:
        from_attributes = True


class FaqItem(BaseModel):
    id: int
    answer: str
    category: Optional[str] = None
    enabled: bool
    questions: list[FaqQuestionItem] = []
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FaqCreateRequest(BaseModel):
    answer: str
    category: Optional[str] = None
    questions: list[str] = []


class FaqUpdateRequest(BaseModel):
    answer: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None
    questions: Optional[list[str]] = None   # 주면 기존 변형을 전부 이 목록으로 교체


class FaqReloadResponse(BaseModel):
    count: int


# ── 미답변 질문 ────────────────────────────────────────────────
class UnansweredItem(BaseModel):
    id: int
    question: str
    rewritten: Optional[str] = None
    topic: Optional[str] = None
    occurrences: int
    status: str
    is_academic: Optional[bool] = None      # None = 아직 선별 전이거나 선별 실패
    triage_reason: Optional[str] = None
    student_id: Optional[int] = None
    faq_id: Optional[int] = None
    created_at: Optional[datetime] = None


class UnansweredCountResponse(BaseModel):
    pending: int


class UnansweredStatusRequest(BaseModel):
    status: Literal["pending", "ignored", "filtered"]


class UnansweredAnswerRequest(BaseModel):
    # 상한을 두는 이유 — 이 답변은 검수를 거치지 않고 학생에게 그대로 나가고, 질문 변형은
    # 하나하나가 FAQ 인덱스의 임베딩 항목이 된다. 개수 제한이 없으면 실수로 대량 입력했을 때
    # 인덱스가 비대해지고 조회가 느려진다.
    answer: str = Field(..., min_length=1, max_length=4000)
    # 학생은 등록된 문장 그대로 묻지 않는다. 원 질문 외에 표현 변형을 함께 받아야
    # 다음에 조금 다르게 물어도 같은 FAQ가 잡힌다.
    extra_questions: list[str] = Field(default_factory=list, max_length=20)


class UnansweredAnswerResponse(BaseModel):
    faq_id: int
    question_count: int
    reloaded: int                            # 재적재된 FAQ 질문 수
    notified: int = 0                        # 알림을 받은 학생 수(이 질문을 기다리던 인원)
