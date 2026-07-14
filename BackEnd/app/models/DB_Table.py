from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON, Date, DateTime, Boolean, Text, Index, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

from app.core.Database import Base

# ==========================================
# 1. 부서/학과 테이블 (department)
# ==========================================
class College(Base):
    """단과대학 (예: 소프트웨어(SW)융합대학)"""
    __tablename__ = "college"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class Division(Base):
    """학부/모집단위 (예: 소프트웨어학부). 학부 없이 단과대학 직속 학과도 있으므로 department에선 nullable."""
    __tablename__ = "division"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    college_id = Column(Integer, ForeignKey("college.id"), nullable=False)

    __table_args__ = (UniqueConstraint("name", "college_id", name="uq_division_name_college"),)


class Department(Base):
    __tablename__ = "department"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    aliases = Column(JSONB)                                     # 학과명 별칭/약칭 매칭용 (예: ["컴공","컴퓨터공학"])
    college_id = Column(Integer, ForeignKey("college.id"))      # 단과대학
    division_id = Column(Integer, ForeignKey("division.id"))    # 학부(모집단위), 직속이면 NULL
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# ==========================================
# 2. 학생 테이블 (student)
# ==========================================
class Student(Base):
    __tablename__ = "student"

    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("department.id"))
    student_no = Column(String, unique=True, nullable=False)  # 학번
    password_hash = Column(String, nullable=False)            # hashed login
    name = Column(String, nullable=False)                     # 이름
    role = Column(String, nullable=False, server_default="student")  # 권한: student / admin
    interests = Column(JSON)                                  # 관심사 태그 (JSONB 대응)

# ==========================================
# 3. 과목 테이블 (course)
# ==========================================
class Course(Base):
    __tablename__ = "course"

    code = Column(String, primary_key=True, unique=True)      # 과목코드
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    credits = Column(Float, nullable=False)                   # 학점 (REAL 대응)

# ==========================================
# 4. 학생 실적 테이블 (student_achievement)
# ==========================================
class StudentAchievement(Base):
    __tablename__ = "student_achievement"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=False) # 실적 연동
    type = Column(String, nullable=False)                     # e.g., 'english_cert', 'thesis'
    value = Column(String)                                    # certificate
    detail = Column(JSON)                                     # JSONB 대응

# ==========================================
# 5. 건물 테이블 (building)
# ==========================================
class Building(Base):
    __tablename__ = "building"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    address = Column(Text)
    aliases = Column(JSONB)
    place_url = Column(Text)
    phone = Column(String(30), nullable=True)                

# ==========================================
# 6. 호실 테이블 (room)
# ==========================================
class Room(Base):
    __tablename__ = "room"

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("building.id"), nullable=False) # 층별실 연동
    room_no = Column(String, nullable=False)
    floor = Column(Integer, nullable=False)
    note = Column(String)                                     # NULL 허용

# ==========================================
# 7. 학과별 요건 세트 테이블 (requirement_set)
# ==========================================
class RequirementSet(Base):
    __tablename__ = "requirement_set"

    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("department.id"), nullable=False) # 학과별 요건 (dept_id)
    admission_year = Column(Integer, nullable=False)                       # 입학년도
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date)                                                # NULL = 현재유효

# ==========================================
# 8. 세부 규칙 테이블 (requirement_rule)
# ==========================================
class RequirementRule(Base):
    __tablename__ = "requirement_rule"

    id = Column(Integer, primary_key=True)
    set_id = Column(Integer, ForeignKey("requirement_set.id"), nullable=False) # 세부 규칙 포함 (set_id)
    min_credits_major = Column(Float, nullable=False)                          # 전공 최소 이수 학점 (REAL)
    min_credits_liberal = Column(Float, nullable=False)                        # 교양 최소 이수 학점 (REAL)
    min_credits_general = Column(Float, nullable=False)                        # 일반 최소 이수 학점 (REAL)
    min_credits_total = Column(Float, nullable=False)                          # 총 최소 이수 학점 (REAL)

# ==========================================
# 9. 장학금 마스터 테이블 (scholarship)
# ==========================================
class Scholarship(Base):
    __tablename__ = "scholarship"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # 장학금 이름
    type = Column(String, nullable=False)          # 장학금 종류
    min_gpa = Column(Float, nullable=False)        # 최소 평점 (REAL)
    min_grade = Column(Integer, nullable=False)    # 최소 학년
    income_level = Column(Integer, nullable=False) # 소득분위 기준
    criteria = Column(JSON)                        # 특수 조건 (JSONB 대응)
    created_at = Column(Integer)                   # ERD상 INTEGER 타입으로 표기됨
    updated_at = Column(Integer)

# ==========================================
# 10. 장학금 신청 내역 테이블 (scholarship_app)
# ==========================================
class ScholarshipApp(Base):
    __tablename__ = "scholarship_app"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=False)       # 장학금 신청 (student_id)
    scholarship_id = Column(Integer, ForeignKey("scholarship.id"), nullable=False) # 신청 장학금 (scholarship_id)
    term = Column(String, nullable=False)                                        # 학기
    result = Column(String, nullable=False)                                      # 신청/선정/탈락 등 상태
    created_at = Column(String)                                                  # ERD상 VARCHAR 타입으로 표기됨
    updated_at = Column(String)

# ==========================================
# 11.  수강 이수 테이블 (student_course)
# ==========================================

class StudentCourse(Base):
    __tablename__ = "student_course"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("student.id"))
    course_code = Column(String, ForeignKey("course.code"))
    is_passed = Column(Boolean, default=True)

# ==========================================
# 12. 채팅 로그 (chat_log)
# ==========================================
class ChatLog(Base):
    __tablename__ = "chat_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=True)
    intent     = Column(String(50), nullable=True)   # campus / graduation / leave / scholarship / dormitory / course_registration / special_credit / general
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_chat_log_created_at", "created_at"),
        Index("ix_chat_log_student_id", "student_id"),
    )

# ==========================================
# 13. JWT 토큰 블랙리스트 (token_blacklist)
# ==========================================
class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(36), unique=True, nullable=False, index=True)  # JWT ID
    expires_at = Column(DateTime(timezone=True), nullable=False)        # 토큰 만료 시각
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# ==========================================
# 14. 채팅 세션 (chat_session)
# ==========================================
class ChatSession(Base):
    __tablename__ = "chat_session"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    student_id     = Column(Integer, ForeignKey("student.id", ondelete="CASCADE"), nullable=False)
    title          = Column(String(100), nullable=True)
    started_at     = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    is_deleted     = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_chat_session_student_id", "student_id"),
    )

# ==========================================
# 15. 채팅 메시지 (chat_message)
# ==========================================
class ChatMessage(Base):
    __tablename__ = "chat_message"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(Integer, ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False)
    student_id  = Column(Integer, ForeignKey("student.id", ondelete="CASCADE"), nullable=False)
    role        = Column(String(20), nullable=False)   # user / assistant
    content     = Column(Text, nullable=False)
    intent      = Column(String(50), nullable=True)
    topic       = Column(String(50), nullable=True)
    source      = Column(String(255), nullable=True)
    source_file = Column(String(255), nullable=True)
    rewritten_query = Column(Text, nullable=True)      # user 메시지의 검색용 재작성 질문 (파인튜닝 데이터용, assistant면 null)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_chat_message_session_id", "session_id"),
        Index("ix_chat_message_created_at", "created_at"),
        Index("ix_chat_message_intent", "intent"),
    )

# ==========================================
# 16. 답변 피드백 (chat_feedback)
# ==========================================
class ChatFeedback(Base):
    __tablename__ = "chat_feedback"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("chat_message.id", ondelete="CASCADE"), unique=True, nullable=False)
    rating     = Column(Integer, nullable=True)   # 1~5
    is_helpful = Column(Boolean, nullable=False)
    comment    = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# ==========================================
# 17. 등록금 납부 테이블 (tuition)
# ==========================================
class Tuition(Base):
    __tablename__ = "tuition"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    student_id     = Column(Integer, ForeignKey("student.id"), nullable=False)
    year           = Column(Integer, nullable=False)           # 연도 (예: 2025)
    semester       = Column(Integer, nullable=False)           # 학기 (1 or 2)
    amount         = Column(Integer, nullable=False)           # 등록금 총액 (원)
    due_date       = Column(Date, nullable=False)              # 납부 기한
    paid_at        = Column(DateTime(timezone=True))           # 납부일 (NULL = 미납)
    status         = Column(String(20), nullable=False, server_default="pending")
                                                               # pending / paid / overdue
    payment_method = Column(String(50))                        # 납부 방법 (계좌이체 등, NULL = 미납)
    receipt_no     = Column(String(50), unique=True)           # 영수증 번호 (NULL = 미납)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_tuition_student_id", "student_id"),
        Index("ix_tuition_year_semester", "year", "semester"),
    )


# ==========================================
# 18. Topic 테이블 (topic)
# ==========================================
class Topic(Base):
    __tablename__ = "topic"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    name         = Column(String(50), unique=True, nullable=False)   # "course_registration"
    label        = Column(String(50), nullable=False)                # "수강신청"
    handler_type = Column(String(30), nullable=False)                # rag / campus / graduation / scholarship / general
    sentences    = Column(JSON, nullable=False, server_default="[]") # 분류 프로토타입 문장 목록
    description  = Column(String(200), nullable=True)
    is_system    = Column(Boolean, default=False, nullable=False, server_default="false")  # True면 삭제 불가
    is_active    = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

# ==========================================
# 19. 행정부서 테이블 (office)
# ==========================================
class Office(Base):
    __tablename__ = "office"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), unique=True, nullable=False)
    phone      = Column(String(30), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# ==========================================
# 20. 건물-행정부서 연결 테이블 (building_contact)
# ==========================================
class BuildingContact(Base):
    __tablename__ = "building_contact"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(Integer, ForeignKey("building.id"), nullable=False)
    office_id   = Column(Integer, ForeignKey("office.id"),   nullable=False)

# ==========================================
# 21. RAG 검색 로그 (retrieval_log)
# ==========================================
class RetrievalLog(Base):
    __tablename__ = "retrieval_log"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    message_id   = Column(Integer, ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False)
    chunk_source = Column(String(255), nullable=True)
    chunk_score  = Column(Float, nullable=True)
    chunk_rank   = Column(Integer, nullable=True)
    topic        = Column(String(50), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_retrieval_log_message_id", "message_id"),
    )

# ==========================================
# 22. 다운로드 파일 테이블 (document_file)
# ==========================================
class DocumentFile(Base):
    __tablename__ = "document_file"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    topic        = Column(String(50), nullable=False)      # 소속 topic
    filename     = Column(String(255), nullable=False)     # 파일명
    content      = Column(LargeBinary, nullable=False)     # 파일 바이트 (bytea)
    content_type = Column(String(100), nullable=True)      # MIME 타입
    size         = Column(Integer, nullable=False)         # 바이트 크기
    description  = Column(String(200), nullable=True)      # (예정) 파일 선택 매칭용
    keywords     = Column(Text, nullable=True)             # (예정) 파일 선택 매칭용
    uploaded_at  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_document_file_topic", "topic"),
        UniqueConstraint("topic", "filename", name="uq_document_file_topic_filename"),
    )
