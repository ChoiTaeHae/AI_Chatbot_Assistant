"""학사일정 라우터 — 사이드바 '학사일정' 위젯용.

채팅 흐름과 별개인 명시적 데이터 조회 (학식 위젯과 같은 패턴).
어드민용 CRUD는 /api/admins/schedule 에 따로 있고, 여기는 조회 전용이다.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.DB_Table import AcademicSchedule, Student
from app.services.school.schedule import _today

router = APIRouter()


def _serialize(rows) -> list[dict]:
    return [
        {
            "id": r.id,
            "event": r.event,
            "start_date": r.start_date.isoformat() if r.start_date else None,
            "end_date": (r.end_date or r.start_date).isoformat() if (r.end_date or r.start_date) else None,
        }
        for r in rows
    ]


@router.get("/schedule/month", summary="월별 학사일정 (사이드바 달력)")
async def schedule_month(
    year: int,
    month: int,
    track: str = "학부",
    current_user: Student = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """해당 월에 '걸치는' 일정 전부 (달력 점 표시용).
    기간 일정이 월 경계를 넘어와도 잡히도록 겹침 조건으로 조회한다."""
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    rows = (await db.execute(
        select(AcademicSchedule)
        .where(AcademicSchedule.track == track)
        .where(and_(AcademicSchedule.start_date <= last, AcademicSchedule.end_date >= first))
        .order_by(AcademicSchedule.start_date)
    )).scalars().all()
    return {"year": year, "month": month, "events": _serialize(rows)}


@router.get("/schedule/upcoming", summary="다가오는 학사일정 (사이드바 고정 목록)")
async def schedule_upcoming(
    limit: int = 3,
    track: str = "학부",
    current_user: Student = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """오늘 기준 진행 중 + 다가오는 일정 (시작일 순)."""
    today = _today()
    rows = (await db.execute(
        select(AcademicSchedule)
        .where(AcademicSchedule.track == track)
        .where(AcademicSchedule.end_date >= today)
        .order_by(AcademicSchedule.start_date)
        .limit(max(1, min(limit, 10)))
    )).scalars().all()
    return {"today": today.isoformat(), "events": _serialize(rows)}
