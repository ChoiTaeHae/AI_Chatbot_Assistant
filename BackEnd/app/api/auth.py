from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.Database import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.services import auth_service

router = APIRouter()


@router.post("/login", response_model=LoginResponse, summary="로그인")
def login(request: LoginRequest, db: Session = Depends(get_db)): #DB를 api에 열어서 서비스에서 사용할 수 있도록(명령에 한번만 실행됨)
    result = auth_service.login(request.student_no, request.password, db) 
    return LoginResponse(**result)


@router.post("/logout", summary="로그아웃")
def logout():
    # TODO: JWT 구현 시 토큰 무효화 처리
    return {"message": "로그아웃 성공"}
