from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_user
from database import get_db
from schemas import LoginRequest

#예시 route post임 

router = APIRouter()

@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = get_user(db, request.username)
    if not user or user.password != request.password:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    return {"message": "Login successful"}

