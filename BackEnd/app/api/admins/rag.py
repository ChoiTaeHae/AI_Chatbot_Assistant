from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.core.topics import TOPICS
from app.schemas.admins import DocumentListResponse, DocumentDeleteResponse
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/topics", summary="토픽 목록 조회")
async def list_topics():
    return TOPICS


@router.post("/documents/upload", summary="문서 업로드 및 RAG 등록")
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form(None),
    topic: str = Form(None),
    doc_date: str = Form(None),
):
    try:
        content     = await file.read()
        source_name = source or Path(file.filename).stem
        job_id      = admin_service.submit_ingest(
            file_content=content,
            filename=file.filename,
            source=source_name,
            topic=topic or None,
            doc_date=doc_date or None,
        )
        return {
            "success":  True,
            "job_id":   job_id,
            "source":   source_name,
            "topic":    topic,
            "file_name": file.filename,
            "message":  f"'{file.filename}' 업로드 완료. 백그라운드에서 RAG 처리 중입니다.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/documents/crawl", summary="URL 크롤링 및 RAG 등록")
async def crawl_document(
    url: str = Form(...),
    source: str = Form(None),
    topic: str = Form(None),
    doc_date: str = Form(None),
):
    try:
        source_name = source or url
        job_id = admin_service.submit_crawl(
            url=url,
            source=source_name,
            topic=topic or None,
            doc_date=doc_date or None,
        )
        return {
            "success": True,
            "job_id": job_id,
            "source": source_name,
            "topic": topic,
            "message": "크롤링 시작. 백그라운드에서 처리 중입니다.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/documents/status/{job_id}", summary="업로드 처리 상태 확인")
async def get_upload_status(job_id: str):
    try:
        return admin_service.get_job_status(job_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/documents", response_model=DocumentListResponse, summary="RAG 문서 목록 조회")
async def list_documents():
    try:
        return admin_service.list_documents()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {e}")


@router.delete("/documents/{source}", response_model=DocumentDeleteResponse, summary="문서 삭제")
async def delete_document(source: str):
    try:
        return admin_service.delete_document(source)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 삭제 중 오류: {e}")
