from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.Database import get_db
from app.services.campus_service import CampusService

router = APIRouter(tags=["Campus"])   # Swagger 문서에서 묶어서 보여줄 태그 이름입니다.
campus_srv = CampusService()

@router.get("/search", summary="학교 위치 및 강의실 안내")
def search_campus_location(keyword : str = Query(..., description="찾고 싶은 건물, 학과, 또는 시설 이름"), db : Session = Depends(get_db)):
    message = campus_srv.search_location(db, keyword)
    return message