from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def login(student_no: str, password: str, db: Session):
    result = db.execute(
        text("SELECT id, student_no, name, dept_id, password_hash FROM student WHERE student_no = :sno"),
        {"sno": student_no}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=401, detail="학번 또는 비밀번호가 틀렸습니다")

    if not verify_password(password, result.password_hash):
        raise HTTPException(status_code=401, detail="학번 또는 비밀번호가 틀렸습니다")

    return {
        "student_no": result.student_no,
        "name": result.name,
        "dept_id": result.dept_id,
    }
