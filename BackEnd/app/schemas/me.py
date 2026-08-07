"""마이페이지 — 학생이 자기 정보를 조회/수정하는 데 쓰는 스키마."""
from typing import Optional

from pydantic import BaseModel, Field

# 장학금 카탈로그(req_major_field)와 같은 어휘를 쓴다. 값이 어긋나면 맞춤 매칭이 조용히 실패한다.
MAJOR_FIELDS = ["인문사회", "예술체육", "이공", "의학계열"]


class DeptOption(BaseModel):
    """학과 선택 드롭다운 항목. major_field는 선택 시 계열을 자동으로 채우는 데 쓴다."""
    id: int
    name: str
    college: Optional[str] = None
    major_field: Optional[str] = None


class MeResponse(BaseModel):
    student_no: str                 # 표시 전용 — 학생이 바꿀 수 없다
    name: str                       # 표시 전용
    role: str
    dept_id: Optional[int] = None
    dept_name: Optional[str] = None
    grade_year: Optional[int] = None
    gpa: Optional[float] = None
    major_field: Optional[str] = None
    interests: list[str] = []


class MeUpdateRequest(BaseModel):
    """주어진 항목만 바꾼다(부분 수정). dept_id를 바꾸면 major_field를 함께 보내지 않는 한
    학과의 계열로 자동 갱신된다."""
    dept_id: Optional[int] = None
    grade_year: Optional[int] = Field(default=None, ge=1, le=4)
    gpa: Optional[float] = Field(default=None, ge=0, le=4.5)
    major_field: Optional[str] = None
    interests: Optional[list[str]] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=64)


# ── 수강 이력 ──────────────────────────────────────────────
class CourseRow(BaseModel):
    """엑셀 파싱 결과 1행 / 수동 추가 입력. 저장 전에는 id가 없다."""
    year: Optional[int] = None
    semester: Optional[str] = None
    course_code: str
    course_name: str
    category: Optional[str] = None
    raw_category: Optional[str] = None      # 엑셀 원본 이수구분 (미리보기 표시용)
    credits: float = 0
    grade: Optional[str] = None
    grade_point: Optional[float] = None
    retake_of: Optional[str] = None
    is_passed: bool = True


class CoursePreviewResponse(BaseModel):
    rows: list[CourseRow]
    total: int
    new_count: int                          # 저장하면 새로 추가될 건수
    duplicate_count: int                    # 이미 있어 건너뛸 건수
    total_credits: float
    gpa_preview: Optional[float] = None      # 이 파일만으로 계산한 평점평균


class CourseCommitRequest(BaseModel):
    rows: list[CourseRow]


class CourseCommitResponse(BaseModel):
    added: int
    skipped: int
    created_courses: int                    # course 테이블에 새로 만든 과목 수
    gpa: Optional[float] = None


class SavedCourse(BaseModel):
    id: int
    year: Optional[int] = None
    semester: Optional[str] = None
    course_code: str
    course_name: str
    category: Optional[str] = None
    credits: float = 0
    grade: Optional[str] = None
    grade_point: Optional[float] = None
    is_passed: bool = True
