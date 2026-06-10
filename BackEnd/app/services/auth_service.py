from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import HTTPException

from app.core.security import create_access_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
