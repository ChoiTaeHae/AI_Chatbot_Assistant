"""
관리자 - 다운로드 파일 관리 라우터

비즈니스 로직은 file_service 에 위임한다. (파일은 공유 DB에 저장)
장학금 파일은 업로드 시 '소속 장학금'을 지정하면 scholarship_file 로 연결된다.
"""
import urllib.parse

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Body
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.services.file_service import file_service
from app.services.school.scholarship_catalog import (
    list_catalog_min, link_file, unlink_file, get_file_links,
)

router = APIRouter()


@router.get("/files", summary="다운로드 파일 목록 조회")
async def list_files(db: AsyncSession = Depends(get_db)):
    data = await file_service.list_files()
    links = await get_file_links(db)   # 장학금 연결 정보 주석
    for arr in data["files"].values():
        for f in arr:
            lk = links.get(f.get("id"))
            if lk:
                f["scholarship_id"] = lk["scholarship_id"]
                f["scholarship_name"] = lk["scholarship_name"]
                f["is_primary"] = lk["is_primary"]
    return data


@router.get("/scholarship-catalog", summary="장학금 목록 (파일 연결 드롭다운용)")
async def scholarship_options(db: AsyncSession = Depends(get_db)):
    return await list_catalog_min(db)


@router.post("/files/upload", summary="파일 업로드 (+장학금 연결)")
async def upload_file(
    file: UploadFile = File(...),
    topic: str = Form(...),
    scholarship_id: int | None = Form(None),
    is_primary: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    try:
        content = await file.read()
        result = await file_service.save_file(topic, file.filename, content, file.content_type)
        if scholarship_id:
            await link_file(db, scholarship_id, result["id"], is_primary)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/files/link", summary="기존 파일을 장학금에 연결")
async def link_scholarship_file(
    document_file_id: int = Body(...),
    scholarship_id: int = Body(...),
    is_primary: bool = Body(False),
    db: AsyncSession = Depends(get_db),
):
    await link_file(db, scholarship_id, document_file_id, is_primary)
    return {"success": True}


@router.delete("/files/link/{document_file_id}", summary="파일-장학금 연결 해제")
async def unlink_scholarship_file(document_file_id: int, db: AsyncSession = Depends(get_db)):
    await unlink_file(db, document_file_id)
    return {"success": True}


@router.delete("/files/{topic}/{filename}", summary="파일 삭제")
async def delete_file(topic: str, filename: str):
    try:
        return await file_service.delete_file(topic, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/files/{topic}/{filename}", summary="파일 다운로드")
async def download_file(topic: str, filename: str):
    try:
        content, fname = await file_service.get_file(topic, filename)
        quoted = urllib.parse.quote(fname)
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
