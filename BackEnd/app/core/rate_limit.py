"""
슬라이딩 윈도우 인메모리 Rate Limiter.

학내 LLM은 GPU 자원이 한정적이므로 사용자당 분당 요청 수를 제한한다.
재시작 시 카운터가 초기화되는 점은 허용 가능한 트레이드오프.

.env 설정:
  RATE_LIMIT_ENABLED=true   # 운영 환경 — 제한 활성화
  RATE_LIMIT_ENABLED=false  # 개발 환경 — 제한 없음
"""
import asyncio
import time
from collections import defaultdict, deque
from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_optional
from app.models.DB_Table import Student

_lock = asyncio.Lock()
# {키: deque([timestamp, ...])} — 로그인은 f"u{student_id}", 게스트는 f"ip{주소}"
_windows: dict[str, deque] = defaultdict(deque)


async def _check(key: str) -> None:
    """슬라이딩 윈도우 검사. 한도를 넘으면 429를 던진다."""
    now = time.monotonic()
    cutoff = now - settings.RATE_LIMIT_WINDOW

    async with _lock:
        window = _windows[key]
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= settings.CHAT_RATE_LIMIT:
            retry_after = int(settings.RATE_LIMIT_WINDOW - (now - window[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"요청이 너무 많습니다. {retry_after}초 후 다시 시도해주세요.",
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)


async def auth_rate_limit(request: Request) -> None:
    """로그인·회원가입용 — IP 단위. 아직 계정이 없거나 누구인지 모르는 단계라 IP밖에 없다.

    채팅과 별도 버킷(auth 접두사)을 쓴다. 한 버킷을 공유하면 질문을 많이 한 사람이
    로그인을 못 하게 되고, 반대로 비밀번호 대입 시도가 채팅 한도를 갉아먹는다.
    RATE_LIMIT_ENABLED=false 면 통과 — 운영에서는 반드시 켜야 한다.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    await _check(f"auth{request.client.host if request.client else 'unknown'}")


async def chat_rate_limit(
    current_user: Student = Depends(get_current_user),
) -> Student:
    """학생 1명당 분당 CHAT_RATE_LIMIT 건 초과 시 429 반환. RATE_LIMIT_ENABLED=false 이면 통과."""
    if not settings.RATE_LIMIT_ENABLED:
        return current_user
    await _check(f"u{current_user.id}")
    return current_user


async def chat_rate_limit_optional(
    request: Request,
    current_user: Student | None = Depends(get_current_user_optional),
) -> Student | None:
    """비로그인 허용 버전. 로그인은 학생 단위, 게스트는 IP 단위로 센다.

    게스트를 한 바구니에 담으면 한 명이 한도를 채웠을 때 나머지 전원이 막힌다.
    학번이 없으니 IP로 가른다 — 완벽하진 않지만(공유 와이파이는 뭉친다) 전원 차단보다 낫다.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return current_user
    if current_user is not None:
        await _check(f"u{current_user.id}")
    else:
        await _check(f"ip{request.client.host if request.client else 'unknown'}")
    return current_user
