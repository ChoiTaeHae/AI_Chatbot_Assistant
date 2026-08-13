"""학생 알림 라우터 — "답변이 등록되면 알려드릴게요"의 수신 쪽.

흐름
    학생 질문 → 답을 못 찾음 → 안내 문구 + 구독 행 생성(faq_service.record)
    → 관리자가 답변 작성 → 구독한 학생 전원에게 notified_at 기록(faq_service.answer_to_faq)
    → 여기서 조회 → 종에 빨간 점 → 눌러서 답변 확인

관리자 쪽 목록(/api/admins/faq/unanswered)과 대칭이지만 라우터를 나눈 이유는 권한이 다르기
때문이다. 저쪽은 모든 학생의 질문을 보고 상태를 바꾸고, 이쪽은 본인 알림만 읽는다.
한 라우터에 두면 관리자 전용 의존성을 엔드포인트마다 걸어야 해서 하나만 빠뜨려도 새어 나간다.

대상을 경로로 받지 않고 토큰의 학생만 다루는 것은 me.py와 같은 원칙이다 —
남의 알림을 지정할 수 있는 경로 자체를 만들지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.schemas.notifications import NotificationCountResponse, NotificationItem
from app.services import faq_service

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationItem],
            summary="내 알림 목록")
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    """답변이 등록된 것만 최근순으로. 아직 답변 전인 구독은 나오지 않는다."""
    return await faq_service.list_notifications(db, current_user.id, limit=limit)


@router.get("/notifications/count", response_model=NotificationCountResponse,
            summary="안 읽은 알림 수")
async def count_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    """종 위 빨간 점 판정용. 폴링으로 자주 불리므로 COUNT 한 번만 한다."""
    return NotificationCountResponse(unread=await faq_service.count_unread(db, current_user.id))


@router.post("/notifications/{notif_id}/read", summary="알림 읽음 처리")
async def read_notification(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    """남의 알림 id를 넣으면 WHERE에 본인 조건이 함께 걸려 아무 행도 바뀌지 않는다 → 404.
    '권한 없음'이 아니라 404로 답하는 것은 그 id가 존재하는지조차 알려 주지 않기 위해서다."""
    if not await faq_service.mark_read(db, current_user.id, notif_id):
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
    return {"ok": True}
