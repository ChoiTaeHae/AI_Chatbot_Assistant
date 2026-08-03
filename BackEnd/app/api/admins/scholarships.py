"""관리자 - 장학금 카탈로그 관리 라우터 ('장학금 관리' 화면).

DBeaver 직접 입력을 대체한다. 장학금 CRUD를 담당하고, 파일 첨부는 files.py의
링크 엔드포인트(/files/link)를 그대로 재사용한다.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.services.school.scholarship_catalog import (
    list_catalog_admin, create_catalog, update_catalog, delete_catalog, list_department_names,
)

router = APIRouter()


class ScholarshipIn(BaseModel):
    name: str
    kind: str = "장학금"             # '장학금' | '근로'
    scope: str                       # '교내' | '교외'
    category: str | None = None
    amount: str | None = None
    eligibility: str | None = None
    period: str | None = None        # 화면 표시용 기간 텍스트
    end_at: datetime | None = None   # 마감 판정용 (KST 벽시계). ISO 문자열 허용
    link: str | None = None
    # 맞춤 설문 매칭 요건 (전부 선택 · None/False = 무관)
    req_region: str | None = None
    req_region_basis: str | None = None
    req_min_gpa: float | None = None
    req_grade: str | None = None
    req_income: str | None = None
    req_age_max: int | None = None
    req_major_field: str | None = None
    req_departments: str | None = None
    req_multichild: bool = False
    req_foreigner: bool = False
    req_disabled: bool = False
    req_independent: bool = False
    req_veteran: bool = False
    req_excellent: bool = False


def _validate(body: ScholarshipIn) -> None:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="이름은 필수입니다.")
    if body.kind not in ("장학금", "근로"):
        raise HTTPException(status_code=400, detail="kind는 '장학금' 또는 '근로'만 가능합니다.")
    if body.scope not in ("교내", "교외"):
        raise HTTPException(status_code=400, detail="scope는 '교내' 또는 '교외'만 가능합니다.")


@router.get("/scholarships", summary="장학금 전체 목록 (관리)")
async def list_scholarships(db: AsyncSession = Depends(get_db)):
    return await list_catalog_admin(db)


@router.get("/departments", summary="학과 목록 (지원 요건 '대상 학과' 다중선택용)")
async def list_departments(db: AsyncSession = Depends(get_db)):
    return await list_department_names(db)


@router.post("/scholarships", summary="장학금 추가")
async def create_scholarship(body: ScholarshipIn, db: AsyncSession = Depends(get_db)):
    _validate(body)
    sid = await create_catalog(db, body.model_dump())
    return {"id": sid, "success": True}


@router.put("/scholarships/{sid}", summary="장학금 수정")
async def update_scholarship(sid: int, body: ScholarshipIn, db: AsyncSession = Depends(get_db)):
    _validate(body)
    ok = await update_catalog(db, sid, body.model_dump())
    if not ok:
        raise HTTPException(status_code=404, detail="장학금을 찾을 수 없습니다.")
    return {"success": True}


@router.delete("/scholarships/{sid}", summary="장학금 삭제")
async def delete_scholarship(sid: int, db: AsyncSession = Depends(get_db)):
    ok = await delete_catalog(db, sid)
    if not ok:
        raise HTTPException(status_code=404, detail="장학금을 찾을 수 없습니다.")
    return {"success": True}
