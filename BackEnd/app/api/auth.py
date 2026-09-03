from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.rate_limit import auth_rate_limit
from app.core.security import decode_access_token
from app.models.DB_Table import TokenBlacklist
from app.schemas.auth import DeptOption, LoginRequest, LoginResponse, SignupRequest
from app.services import auth_service

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.post("/login", response_model=LoginResponse, summary="로그인")
async def login(
    request: LoginRequest,
    http: Request,
    db: AsyncSession = Depends(get_db),
):
    # 로그인도 IP 단위로 센다 — 없으면 비밀번호를 무한정 대입해 볼 수 있다.
    await auth_rate_limit(http)
    result = await auth_service.login(request.student_no, request.password, db)
    return LoginResponse(**result)


@router.post("/signup", response_model=LoginResponse, summary="회원가입")
async def signup(
    request: SignupRequest,
    http: Request,
    db: AsyncSession = Depends(get_db),
):
    """가입 후 곧바로 로그인 상태가 된다(토큰 발급). 권한은 항상 student.

    가입 자체를 IP 단위로 제한한다. 학번만 있으면 계정이 만들어지는 구조라
    제한이 없으면 스크립트로 대량 생성이 가능하다.
    """
    await auth_rate_limit(http)
    result = await auth_service.signup(
        request.student_no, request.password, request.name, request.dept_id, db
    )
    return LoginResponse(**result)


@router.get("/departments", response_model=list[DeptOption], summary="학과 목록 (가입 화면용)")
async def signup_departments(db: AsyncSession = Depends(get_db)):
    """로그인 전에 필요한 목록이라 인증 없이 연다. id·이름만 나간다."""
    return await auth_service.list_departments_public(db)


@router.post("/logout", summary="로그아웃")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """토큰을 블랙리스트에 등록해 즉시 무효화"""
    try:
        payload = decode_access_token(credentials.credentials)
        jti: str | None = payload.get("jti")
        exp: int | None = payload.get("exp")
        if jti and exp:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
            await db.commit()
    except Exception:
        pass  # 이미 만료된 토큰이어도 로그아웃은 성공 처리
    return {"message": "로그아웃 성공"}
