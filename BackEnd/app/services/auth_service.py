from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from app.core.security import create_access_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """비밀번호 해시 생성 — 마이페이지 비밀번호 변경에서 사용."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def login(student_no: str, password: str, db: AsyncSession):
    result = await db.execute(
        text("SELECT id, student_no, name, dept_id, role, password_hash FROM student WHERE student_no = :sno"),
        {"sno": student_no}
    )
    student = result.fetchone()

    if not student:
        raise HTTPException(status_code=401, detail="학번 또는 비밀번호가 틀렸습니다")

    if not verify_password(password, student.password_hash):
        raise HTTPException(status_code=401, detail="학번 또는 비밀번호가 틀렸습니다")

    role = student.role or "student"
    access_token = create_access_token({"sub": student.student_no, "role": role})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "student_no": student.student_no,
        "name": student.name,
        "dept_id": student.dept_id,
        "role": role,
    }


async def list_departments_public(db: AsyncSession) -> list[dict]:
    """가입 화면 학과 드롭다운용. 로그인 전에 필요하므로 인증 없이 연다.

    학과 목록은 학교 홈페이지에도 공개돼 있고 챗봇이 '학과 안내'로 이미 답하는 내용이라
    감출 정보가 아니다. id와 이름만 내보낸다(연락처·홈페이지는 여기서 쓸 일이 없다).
    """
    rows = (await db.execute(
        text("SELECT id, name FROM department ORDER BY name")
    )).fetchall()
    return [{"id": r.id, "name": r.name} for r in rows]


async def signup(student_no: str, password: str, name: str, dept_id: int, db: AsyncSession):
    """학생 계정 생성 후 바로 로그인 상태로 만들어 준다(토큰 발급).

    role은 인자로 받지 않는다 — 항상 'student'다. 관리자 승격은 관리자 화면에서만 한다
    (/api/admins/users/{id}/role). 가입 입력으로 권한을 정하게 두면 그 자체가 권한 상승 경로다.
    """
    exists = (await db.execute(
        text("SELECT 1 FROM student WHERE student_no = :sno"), {"sno": student_no}
    )).fetchone()
    if exists:
        raise HTTPException(status_code=409, detail="이미 가입된 학번입니다.")

    dept = (await db.execute(
        text("SELECT id FROM department WHERE id = :did"), {"did": dept_id}
    )).fetchone()
    if not dept:
        raise HTTPException(status_code=400, detail="학과를 다시 선택해 주세요.")

    try:
        row = (await db.execute(
            text("""INSERT INTO student (student_no, password_hash, name, dept_id, role)
                    VALUES (:sno, :pw, :name, :did, 'student')
                    RETURNING id, student_no, name, dept_id, role"""),
            {"sno": student_no, "pw": hash_password(password), "name": name, "did": dept_id},
        )).fetchone()
        await db.commit()
    except IntegrityError:
        # 동시에 같은 학번으로 두 번 눌린 경우 — 위 조회와 INSERT 사이의 틈을 unique 제약이 막는다.
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 가입된 학번입니다.")

    return {
        "access_token": create_access_token({"sub": row.student_no, "role": row.role}),
        "token_type": "bearer",
        "student_no": row.student_no,
        "name": row.name,
        "dept_id": row.dept_id,
        "role": row.role,
        "message": "회원가입 완료",
    }
