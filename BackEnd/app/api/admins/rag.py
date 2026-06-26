from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.admins import (
    DocumentListResponse,
    DocumentDeleteResponse,
    TopicItem,
    TopicCreateRequest,
    TopicUpdateRequest,
)
from app.services.admin_service import admin_service

router = APIRouter()


# ── Topic CRUD ─────────────────────────────────────────────────────

@router.get("/topics", response_model=list[TopicItem], summary="토픽 목록 조회")
async def list_topics(db: AsyncSession = Depends(get_db)):
    return await admin_service.list_topics(db)


@router.post("/topics", response_model=TopicItem, summary="토픽 추가")
async def create_topic(body: TopicCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.create_topic(db, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/topics/{topic_name}", response_model=TopicItem, summary="토픽 수정")
async def update_topic(topic_name: str, body: TopicUpdateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.update_topic(db, topic_name, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/topics/{topic_name}", summary="토픽 삭제")
async def delete_topic(topic_name: str, db: AsyncSession = Depends(get_db)):
    try:
        await admin_service.delete_topic(db, topic_name)
        return {"success": True, "name": topic_name}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── RAG 문서 관리 ──────────────────────────────────────────────────

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
