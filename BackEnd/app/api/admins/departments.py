"""관리자 - 학과 관리 라우터 ('학과 관리' 화면).

단과대학(College) / 학부(Division) / 학과(Department) 계층을 관리한다. 챗봇 '학과 소개'가
읽는 테이블과 동일하며, 서비스에서 변경 시 캐시를 무효화해 챗봇에 바로 반영된다.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.services.school import department_admin as svc

router = APIRouter()


# ─────────────── 입력 모델 ───────────────
class CollegeIn(BaseModel):
    name: str


class DivisionIn(BaseModel):
    name: str
    college_id: int


class DepartmentIn(BaseModel):
    name: str
    college_id: int | None = None
    division_id: int | None = None
    aliases: list[str] = []
    homepage_url: str | None = None
    phone: str | None = None


# ─────────────── 트리 조회 ───────────────
@router.get("/dept/tree", summary="학과 트리 (단과대학→학부→학과)")
async def dept_tree(db: AsyncSession = Depends(get_db)):
    return await svc.get_dept_tree(db)


# ─────────────── 단과대학 ───────────────
@router.post("/dept/college", summary="단과대학 추가")
async def create_college(body: CollegeIn, db: AsyncSession = Depends(get_db)):
    try:
        cid = await svc.create_college(db, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": cid, "success": True}


@router.put("/dept/college/{cid}", summary="단과대학 수정")
async def update_college(cid: int, body: CollegeIn, db: AsyncSession = Depends(get_db)):
    try:
        ok = await svc.update_college(db, cid, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="단과대학을 찾을 수 없습니다.")
    return {"success": True}


@router.delete("/dept/college/{cid}", summary="단과대학 삭제")
async def delete_college(cid: int, db: AsyncSession = Depends(get_db)):
    try:
        ok = await svc.delete_college(db, cid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="단과대학을 찾을 수 없습니다.")
    return {"success": True}


# ─────────────── 학부 ───────────────
@router.post("/dept/division", summary="학부 추가")
async def create_division(body: DivisionIn, db: AsyncSession = Depends(get_db)):
    try:
        did = await svc.create_division(db, body.name, body.college_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": did, "success": True}


@router.put("/dept/division/{did}", summary="학부 수정")
async def update_division(did: int, body: DivisionIn, db: AsyncSession = Depends(get_db)):
    try:
        ok = await svc.update_division(db, did, body.name, body.college_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="학부를 찾을 수 없습니다.")
    return {"success": True}


@router.delete("/dept/division/{did}", summary="학부 삭제")
async def delete_division(did: int, db: AsyncSession = Depends(get_db)):
    try:
        ok = await svc.delete_division(db, did)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="학부를 찾을 수 없습니다.")
    return {"success": True}


# ─────────────── 학과 ───────────────
@router.post("/dept/department", summary="학과 추가")
async def create_department(body: DepartmentIn, db: AsyncSession = Depends(get_db)):
    try:
        did = await svc.create_department(db, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": did, "success": True}


@router.put("/dept/department/{did}", summary="학과 수정")
async def update_department(did: int, body: DepartmentIn, db: AsyncSession = Depends(get_db)):
    try:
        res = await svc.update_department(db, did, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if res is False:
        raise HTTPException(status_code=404, detail="학과를 찾을 수 없습니다.")
    return {"success": True, **res}


@router.delete("/dept/department/{did}", summary="학과 삭제")
async def delete_department(did: int, db: AsyncSession = Depends(get_db)):
    try:
        ok = await svc.delete_department(db, did)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="학과를 찾을 수 없습니다.")
    return {"success": True}
