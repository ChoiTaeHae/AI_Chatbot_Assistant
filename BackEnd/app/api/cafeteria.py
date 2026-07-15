"""
학식(카페테리아) 라우터 — 사이드바 '오늘의 학식' 위젯용.

채팅 흐름과 별개인 명시적 데이터 조회 (졸업 현황 status 엔드포인트와 같은 패턴).
학식은 개인정보가 아니지만, 사이드바가 로그인 화면에만 있으므로 로그인 필요로 둔다.
"""
import asyncio
import traceback

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.school.cafeteria import get_today_menu, get_week_menu

router = APIRouter()


@router.get("/cafeteria/today", summary="오늘의 학식 (사이드바 위젯)")
async def cafeteria_today(
    restaurant: str | None = None,
    current_user: Student = Depends(get_current_user),
):
    try:
        # get_menu_data()가 blocking(크롤/캐시)이라 스레드로 분리
        return await asyncio.to_thread(get_today_menu, restaurant)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="학식 정보를 불러오지 못했어요.")


@router.get("/cafeteria/week", summary="주간 학식 (더보기)")
async def cafeteria_week(
    current_user: Student = Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(get_week_menu)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="학식 정보를 불러오지 못했어요.")
