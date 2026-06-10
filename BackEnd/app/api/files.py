"""
학생용 파일 다운로드 라우터

로그인한 학생이면 누구나 접근 가능. (관리자 전용 아님)
관리자 파일 관리는 app/api/admins/files.py 에서 처리.
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.file_service import file_service

router = APIRouter()


@router.get("/files/{topic}/{filename}", summary="파일 다운로드 (로그인 필요)")
async def download_file(
    topic: str,
    filename: str,
    current_user: Student = Depends(get_current_user),
):
    try:
        path = file_service.get_file_path(topic, filename)
        return FileResponse(
            path=path,
            filename=filename,
            media_type="application/octet-stream",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
