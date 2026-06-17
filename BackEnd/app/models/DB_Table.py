from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON, Date, DateTime, Boolean, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

from app.core.Database import Base

# ==========================================
# 1. 부서/학과 테이블 (department)
# ==========================================
class Department(Base):
    __tablename__ = "department"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
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
