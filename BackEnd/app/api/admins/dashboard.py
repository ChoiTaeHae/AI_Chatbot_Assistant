from fastapi import APIRouter, HTTPException

from app.schemas.admins import DashboardResponse
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse, summary="대시보드 요약 정보")
async def get_dashboard():
    try:
        return admin_service.get_dashboard()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"대시보드 조회 실패: {e}")
