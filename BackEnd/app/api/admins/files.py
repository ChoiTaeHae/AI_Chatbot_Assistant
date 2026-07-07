"""
관리자 - 다운로드 파일 관리 라우터

비즈니스 로직은 file_service 에 위임한다. (파일은 공유 DB에 저장)
"""
import urllib.parse

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response

from app.services.file_service import file_service

router = APIRouter()


@router.get("/files", summary="다운로드 파일 목록 조회")
async def list_files():
    return await file_service.list_files()


@router.post("/files/upload", summary="파일 업로드")
async def upload_file(
    file: UploadFile = File(...),
    topic: str = Form(...),
):
    try:
        content = await file.read()
        return await file_service.save_file(topic, file.filename, content, file.content_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
