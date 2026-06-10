from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.services import auth_service
from app.core.security import blacklist_token

router = APIRouter()
security = HTTPBearer()

@router.post("/login", response_model=LoginResponse, summary="로그인")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await auth_service.login(request.student_no, request.password, db)
    return LoginResponse(**result)


@router.post("/logout", summary="로그아웃")
def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    blacklist_token(credentials.credentials)
    return {"message": "로그아웃 성공"}
