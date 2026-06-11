from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.security import decode_access_token
from app.models.DB_Table import TokenBlacklist
from app.schemas.auth import LoginRequest, LoginResponse
from app.services import auth_service

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.post("/login", response_model=LoginResponse, summary="로그인")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await auth_service.login(request.student_no, request.password, db)
    return LoginResponse(**result)


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
