"""
JWT 토큰 생성 / 검증
"""
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException
from app.core.config import settings

ALGORITHM = "HS256"

_token_blacklist: set[str] = set()  # 블랙리스트(서버 재시작 시 초기화됨)

def blacklist_token(token: str) -> None:
    _token_blacklist.add(token)

def is_token_blacklisted(token: str) -> bool:
    return token in _token_blacklist


def create_access_token(data: dict) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    """JWT 디코딩 — 실패 시 JWTError 발생. 블랙리스트 토큰은 거부."""
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="로그아웃된 토큰입니다")
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])