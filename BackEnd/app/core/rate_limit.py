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
from fastapi import Depends, HTTPException

from app.core.config import settings
from app.core.deps import get_current_user
from app.models.DB_Table import Student

_lock = asyncio.Lock()
# {student_id: deque([timestamp, ...])}
_windows: dict[int, deque] = defaultdict(deque)


async def chat_rate_limit(
    current_user: Student = Depends(get_current_user),
) -> Student:
    """학생 1명당 분당 CHAT_RATE_LIMIT 건 초과 시 429 반환. RATE_LIMIT_ENABLED=false 이면 통과."""
    if not settings.RATE_LIMIT_ENABLED:
        return current_user

    user_id = current_user.id
    now = time.monotonic()
    cutoff = now - settings.RATE_LIMIT_WINDOW

    async with _lock:
        window = _windows[user_id]
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= settings.CHAT_RATE_LIMIT:
            oldest = window[0]
            retry_after = int(settings.RATE_LIMIT_WINDOW - (now - oldest)) + 1
            raise HTTPException(
                status_code=429,
                detail=f"요청이 너무 많습니다. {retry_after}초 후 다시 시도해주세요.",
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)

    return current_user
