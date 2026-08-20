"""
학식(다이닝) 라우터 — 사이드바 '오늘의 학식' 위젯용.

채팅 흐름과 별개인 명시적 데이터 조회 (졸업 현황 status 엔드포인트와 같은 패턴).
학식은 개인정보가 아니라 누가 봐도 같은 정보다. 예전엔 사이드바가 로그인한 화면에만
있어서 로그인 필요로 뒀지만, 비로그인 둘러보기가 생기면서 그 전제가 사라졌다.
채팅으로는 "오늘 학식 뭐야?"에 답하면서 사이드바 위젯만 막으면 앞뒤가 안 맞는다.
"""
import asyncio
import traceback

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user_optional
from app.models.DB_Table import Student
from app.services.school.dining import get_today_menu, get_week_menu

router = APIRouter()


@router.get("/dining/today", summary="오늘의 학식 (사이드바 위젯)")
async def dining_today(
    restaurant: str | None = None,
    current_user: Student | None = Depends(get_current_user_optional),
):
    try:
        # get_menu_data()가 blocking(크롤/캐시)이라 스레드로 분리
        return await asyncio.to_thread(get_today_menu, restaurant)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="학식 정보를 불러오지 못했어요.")


@router.get("/dining/week", summary="주간 학식 (더보기)")
async def dining_week(
    current_user: Student | None = Depends(get_current_user_optional),
):
    try:
        return await asyncio.to_thread(get_week_menu)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="학식 정보를 불러오지 못했어요.")
