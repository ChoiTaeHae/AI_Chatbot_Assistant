"""
FastAPI 의존성 — 인증/권한 검사

사용법:
    @router.get("/...", dependencies=[Depends(get_current_user)])   # 로그인 필요
    @router.get("/...", dependencies=[Depends(require_admin)])       # 관리자 필요
    async def endpoint(current_user: Student = Depends(get_current_user)):  # 유저 정보 필요
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.Database import get_db
from app.core.security import decode_access_token
from app.models.DB_Table import Student

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Student:
    """Bearer 토큰 검증 후 Student 반환"""
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        student_no: str | None = payload.get("sub")
        if not student_no:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")

    result = await db.execute(select(Student).where(Student.student_no == student_no))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자를 찾을 수 없습니다")
    return student


async def require_admin(
    current_user: Student = Depends(get_current_user),
) -> Student:
    """관리자 권한 검사"""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다")
    return current_user
