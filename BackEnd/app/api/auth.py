from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.Database import get_db

router = APIRouter()


@router.post("/login", summary="로그인")
def login(db: Session = Depends(get_db)):
    # TODO: auth_service 완성되면 연결
    # token = auth_service.login(request, db)
    # return {"access_token": token}
    raise HTTPException(status_code=501, detail="auth_service 미구현")


@router.post("/logout", summary="로그아웃")
def logout():
    # TODO: auth_service 완성되면 연결
    raise HTTPException(status_code=501, detail="auth_service 미구현")
