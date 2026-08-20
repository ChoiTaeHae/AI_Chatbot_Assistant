"""
학생용 파일 다운로드 라우터

비로그인도 받을 수 있다. document_file에는 학생별로 다른 파일이 없고 전원이 공유하는
빈 서식(휴학원·공결신청서 등)만 들어 있어, 로그인을 요구할 근거가 없다. 학교 홈페이지에서도
받을 수 있는 자료다. 개인 데이터가 섞이는 순간 이 판단은 다시 해야 한다.

관리자 파일 관리(업로드·삭제)는 app/api/admins/files.py 에서 처리 — 그쪽은 관리자 전용.

파일은 document_file 테이블(공유 DB)에 저장되며, 여기서는 바이트를 그대로 반환한다.
"""
import urllib.parse

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response

from app.core.deps import get_current_user_optional
from app.models.DB_Table import Student
from app.services.file_service import file_service

router = APIRouter()


@router.get("/files/{topic}/{filename}", summary="파일 다운로드 (비로그인 가능)")
async def download_file(
    topic: str,
    filename: str,
    current_user: Student | None = Depends(get_current_user_optional),
):
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
