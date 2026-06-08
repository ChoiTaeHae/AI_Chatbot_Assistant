from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.DB_Table import Building


class CampusService:
    async def search_location(self, db: AsyncSession, keyword: str):
        result = await db.execute(
            select(Building).where(Building.name.ilike(f"%{keyword}%"))
        )
        building = result.scalar_one_or_none()

        if not building:
            return {"msg": f"'{keyword}' 관련 위치를 찾을 수 없습니다. 정확한 건물명이나 학과를 입력해주세요."}

        return {"msg": f"[{building.name}] 위도: {building.latitude}, 경도: {building.longitude}"}
