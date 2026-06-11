from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.schemas.admins import StatsResponse, ChatStatsResponse
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/stats", response_model=StatsResponse, summary="DB 현황 통계 조회")
async def get_stats(db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.get_stats(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {e}")


@router.get("/chat-stats", response_model=ChatStatsResponse, summary="채팅 사용 통계 조회")
async def get_chat_stats(db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.get_chat_stats(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채팅 통계 조회 실패: {e}")
