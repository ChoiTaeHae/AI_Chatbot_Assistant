from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.Database import get_db
from app.services.campus_service import CampusService

router = APIRouter(tags=["Campus"])
campus_srv = CampusService()


@router.get("/search", summary="학교 위치 및 건물 안내")
async def search_campus_location(
    keyword: str = Query(..., description="찾고자 하는 건물, 학과, 또는 시설 이름"),
    db: AsyncSession = Depends(get_db)
):
    return await campus_srv.search_location(db, keyword)