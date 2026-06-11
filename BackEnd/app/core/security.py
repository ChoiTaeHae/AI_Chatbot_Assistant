"""
JWT 토큰 생성 / 검증
"""
import uuid
from datetime import datetime, timedelta

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(data: dict) -> str:
    """JWT 액세스 토큰 생성 — jti(고유 ID) 포함"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    to_encode["jti"] = str(uuid.uuid4())  # 토큰별 고유 ID (블랙리스트용)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """JWT 디코딩 — 실패 시 JWTError 발생"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
