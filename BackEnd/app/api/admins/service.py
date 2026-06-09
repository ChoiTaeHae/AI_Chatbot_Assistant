from fastapi import APIRouter

from app.schemas.admins import SettingsResponse
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse, summary="서비스 설정 조회")
async def get_settings():
    return admin_service.get_settings()
