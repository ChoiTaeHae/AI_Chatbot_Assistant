from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.schemas.admins import UserItem, UserListResponse, RoleUpdate
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/users", response_model=UserListResponse, summary="사용자 목록 조회")
async def get_users(db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.get_users(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 실패: {e}")


@router.patch("/users/{user_id}/role", response_model=UserItem, summary="사용자 권한 변경")
async def update_user_role(
    user_id: int,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_service.update_user_role(db, user_id, body.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
