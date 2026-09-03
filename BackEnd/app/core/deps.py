"""
FastAPI 의존성 — 인증/권한 검사

사용법:
    @router.get("/...", dependencies=[Depends(get_current_user)])   # 로그인 필요
    @router.get("/...", dependencies=[Depends(require_admin)])       # 관리자 필요
    async def endpoint(current_user: Student = Depends(get_current_user)):  # 유저 정보 필요
    async def endpoint(user: Student | None = Depends(get_current_user_optional)):  # 비로그인 허용
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.Database import get_db
from app.core.security import decode_access_token
from app.models.DB_Table import Student, TokenBlacklist

bearer_scheme = HTTPBearer()

# 비로그인 허용 엔드포인트용 — 헤더가 없어도 403을 던지지 않고 None을 준다.
# 별도 인스턴스를 두는 이유: auto_error는 스킴 단위 설정이라 기존 bearer_scheme을
# 끄면 로그인 필수 엔드포인트까지 전부 401 대신 None을 받게 된다.
bearer_scheme_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Student:
    """Bearer 토큰 검증 후 Student 반환. 블랙리스트 토큰은 401 반환."""
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        student_no: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        if not student_no or not jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")

    # 블랙리스트 확인 (로그아웃된 토큰 차단)
    blacklisted = await db.execute(
        select(TokenBlacklist).where(TokenBlacklist.jti == jti)
    )
    if blacklisted.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그아웃된 토큰입니다")

    result = await db.execute(select(Student).where(Student.student_no == student_no))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자를 찾을 수 없습니다")
    return student


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Student | None:
    """토큰이 있으면 Student, 없거나 못 쓰는 토큰이면 None (게스트).

    비로그인으로도 쓸 수 있는 엔드포인트(채팅·서식 다운로드)에서 쓴다.
    만료·로그아웃된 토큰도 401이 아니라 None으로 떨어뜨린다 — 토큰이 만료됐다는 이유로
    화면이 통째로 막히면, 게스트로도 쓸 수 있는 기능까지 못 쓰게 된다.
    호출 측은 반드시 None을 처리해야 한다(개인 데이터 접근은 각 핸들러가 따로 막는다).
    """
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        student_no: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        if not student_no or not jti:
            return None
    except JWTError:
        return None

    blacklisted = await db.execute(select(TokenBlacklist).where(TokenBlacklist.jti == jti))
    if blacklisted.scalar_one_or_none():
        return None

    result = await db.execute(select(Student).where(Student.student_no == student_no))
    return result.scalar_one_or_none()


async def require_admin(
    current_user: Student = Depends(get_current_user),
) -> Student:
    """관리자 권한 검사"""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다")
    return current_user
