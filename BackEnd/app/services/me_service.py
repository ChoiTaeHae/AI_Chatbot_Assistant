"""마이페이지 서비스 — 학생이 자기 정보를 조회/수정하는 로직.

학번·이름은 신원이라 바꿀 수 없고(표시 전용), 학과·학년·학점·전공계열·관심목록만 수정한다.

학년·학점·전공계열을 학생이 고칠 수 있게 한 이유
    이 세 값은 맞춤 장학금 매칭에 그대로 쓰이는데, 실제 성적 시스템 연동이 없어 서버 기동 시
    학번 id 기반 더미로 채워진다(server.py). 학생이 직접 고치지 못하면 매칭이 자기와 무관한
    값으로 계산된다.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import Student, Department, College
from app.schemas.me import (
    MeResponse,
    MeUpdateRequest,
    PasswordChangeRequest,
    DeptOption,
    MAJOR_FIELDS,
)
from app.services.auth_service import verify_password, hash_password


class MeService:

    # ── 조회 ────────────────────────────────────────────────
    async def get_me(self, db: AsyncSession, student: Student) -> MeResponse:
        return self._to_response(student, await self._dept_name(db, student.dept_id))

    async def list_departments(self, db: AsyncSession) -> list[DeptOption]:
        """학과 선택 드롭다운용. major_field를 함께 내려 화면에서 학과를 고르는 순간
        계열을 채운다(서버 왕복 없이)."""
        rows = (await db.execute(
            select(Department.id, Department.name, College.name, Department.major_field)
            .outerjoin(College, College.id == Department.college_id)
            .order_by(College.name, Department.name)
        )).all()
        return [DeptOption(id=i, name=n, college=c, major_field=f) for i, n, c, f in rows]

    # ── 수정 ────────────────────────────────────────────────
    async def update_me(self, db: AsyncSession, student_id: int,
                        body: MeUpdateRequest) -> MeResponse:
        student = (await db.execute(
            select(Student).where(Student.id == student_id))).scalar_one()

        if body.dept_id is not None:
            dept = (await db.execute(
                select(Department).where(Department.id == body.dept_id))).scalar_one_or_none()
            if not dept:
                raise ValueError("존재하지 않는 학과입니다.")
            student.dept_id = dept.id
            # 학과를 바꾸면 계열도 따라간다 — 단, 같은 요청에 계열이 함께 왔으면 그쪽을 존중한다
            # (학과 규칙이 못 맞추는 예외를 학생이 직접 고칠 수 있어야 하므로).
            if body.major_field is None and dept.major_field:
                student.major_field = dept.major_field

        if body.major_field is not None:
            if body.major_field not in MAJOR_FIELDS:
                raise ValueError(f"전공계열은 {' / '.join(MAJOR_FIELDS)} 중 하나여야 합니다.")
            student.major_field = body.major_field

        if body.grade_year is not None:
            student.grade_year = body.grade_year
        if body.gpa is not None:
            student.gpa = body.gpa
        if body.interests is not None:
            student.interests = self._clean_interests(body.interests)

        await db.commit()
        await db.refresh(student)
        return self._to_response(student, await self._dept_name(db, student.dept_id))

    async def change_password(self, db: AsyncSession, student_id: int,
                              body: PasswordChangeRequest) -> None:
        student = (await db.execute(
            select(Student).where(Student.id == student_id))).scalar_one()

        if not verify_password(body.current_password, student.password_hash):
            raise ValueError("현재 비밀번호가 일치하지 않습니다.")
        if body.current_password == body.new_password:
            raise ValueError("새 비밀번호가 기존과 같습니다.")

        student.password_hash = hash_password(body.new_password)
        await db.commit()
        # 토큰은 그대로 둔다 — 비밀번호를 바꿨다고 지금 쓰는 세션을 끊으면 곧바로 다시
        # 로그인해야 해서 불편하다. 다른 기기 세션까지 끊으려면 로그아웃(블랙리스트)을 쓴다.

    # ── 내부 ────────────────────────────────────────────────
    @staticmethod
    async def _dept_name(db: AsyncSession, dept_id: int | None) -> str | None:
        if not dept_id:
            return None
        return await db.scalar(select(Department.name).where(Department.id == dept_id))

    @staticmethod
    def _to_response(student: Student, dept_name: str | None) -> MeResponse:
        return MeResponse(
            student_no=student.student_no,
            name=student.name,
            role=student.role,
            dept_id=student.dept_id,
            dept_name=dept_name,
            grade_year=student.grade_year,
            gpa=student.gpa,
            major_field=student.major_field,
            interests=list(student.interests or []),
        )

    @staticmethod
    def _clean_interests(items: list[str]) -> list[str]:
        """공백 제거 + 빈 값 제거 + 중복 제거(입력 순서 유지). 화면에서 자유 입력이라 정리해 저장."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in items:
            t = (raw or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out


# 싱글톤 인스턴스
me_service = MeService()
