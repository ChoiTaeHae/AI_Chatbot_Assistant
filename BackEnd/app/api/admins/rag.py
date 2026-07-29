from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.admins import (
    DocumentListResponse,
    DocumentDeleteResponse,
    DocumentUpdateRequest,
    DocumentUpdateResponse,
    ChunkListResponse,
    ChunkUpdateRequest,
    ChunkUpdateResponse,
    TopicItem,
    TopicCreateRequest,
    TopicUpdateRequest,
    ScheduleItem,
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    ScheduleGateConfig,
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
    url: str = Form(None),
    contact_name: str = Form(None),
    contact_phone: str = Form(None),
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
            url=url or None,
            contact_name=contact_name or None,
            contact_phone=contact_phone or None,
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
    contact_name: str = Form(None),
    contact_phone: str = Form(None),
):
    try:
        source_name = source or url
        job_id = admin_service.submit_crawl(
            url=url,
            source=source_name,
            topic=topic or None,
            doc_date=doc_date or None,
            contact_name=contact_name or None,
            contact_phone=contact_phone or None,
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


# ── 학사일정 관리 ──────────────────────────────────────────────────

@router.post("/schedule/crawl", summary="학사일정 URL 크롤링 및 DB 적재")
async def crawl_schedule(
    url: str = Form(...),
    keep_recent_years: int = Form(2),
    db: AsyncSession = Depends(get_db),
):
    """학사일정 페이지(haksa_list.jsp 등)를 크롤·파싱해 academic_schedule에 적재.
    임베딩이 없어 가볍기 때문에 백그라운드 job 없이 바로 처리하고 적재 건수를 반환한다.
    같은 URL 재크롤 시 기존 데이터를 교체(멱등)."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="유효하지 않은 URL 형식입니다.")
    try:
        from app.services.school.schedule import schedule_service
        count = await schedule_service.ingest_from_url(url, db, keep_recent_years=keep_recent_years)
        return {
            "success": True,
            "url": url,
            "count": count,
            "message": f"학사일정 {count}건 적재 완료.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학사일정 크롤링 실패: {e}")


@router.get("/schedule", response_model=list[ScheduleItem], summary="학사일정 목록 조회")
async def list_schedules(
    track: str = None,
    academic_year: int = None,
    db: AsyncSession = Depends(get_db),
):
    from app.services.school.schedule import schedule_service
    return await schedule_service.list_schedules(db, track=track or None, academic_year=academic_year or None)


@router.post("/schedule", response_model=ScheduleItem, summary="학사일정 추가")
async def create_schedule(body: ScheduleCreateRequest, db: AsyncSession = Depends(get_db)):
    from app.services.school.schedule import schedule_service
    return await schedule_service.create_schedule(db, body.model_dump())


@router.patch("/schedule/{schedule_id}", response_model=ScheduleItem, summary="학사일정 수정")
async def update_schedule(schedule_id: int, body: ScheduleUpdateRequest, db: AsyncSession = Depends(get_db)):
    from app.services.school.schedule import schedule_service
    try:
        return await schedule_service.update_schedule(db, schedule_id, body.model_dump(exclude_unset=True))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/schedule/{schedule_id}", summary="학사일정 삭제")
async def delete_schedule(schedule_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.school.schedule import schedule_service
    try:
        await schedule_service.delete_schedule(db, schedule_id)
        return {"success": True, "id": schedule_id}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/schedule/gate", response_model=ScheduleGateConfig, summary="학사일정 날짜-게이트 키워드 조회")
async def get_schedule_gate(db: AsyncSession = Depends(get_db)):
    from app.services.school.schedule import schedule_service
    return await schedule_service.get_gate_config(db)


@router.put("/schedule/gate", response_model=ScheduleGateConfig, summary="학사일정 날짜-게이트 키워드 저장(즉시 반영)")
async def put_schedule_gate(body: ScheduleGateConfig, db: AsyncSession = Depends(get_db)):
    from app.services.school.schedule import schedule_service
    return await schedule_service.update_gate_config(db, body.date_intent, body.event_keywords)


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


@router.patch("/documents/{source}", response_model=DocumentUpdateResponse, summary="문서 메타데이터 수정")
async def update_document(source: str, body: DocumentUpdateRequest):
    """주제 분류·기준 날짜·출처 URL·담당 부서·전화번호를 수정한다.

    본문과 임베딩은 그대로 두고 payload만 갱신하므로 재인제스트가 없다
    (기존에는 메타 하나를 고치려면 삭제 후 재업로드뿐이라 청크가 전부 다시 만들어졌다).
    """
    try:
        return admin_service.update_document(source, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 수정 중 오류: {e}")


@router.get("/documents/{source}/chunks", response_model=ChunkListResponse, summary="문서 청크 목록 조회")
async def list_document_chunks(source: str):
    """문서가 실제로 어떻게 쪼개져 저장됐는지 조회한다(본문 포함, 벡터 제외)."""
    try:
        return admin_service.list_chunks(source)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"청크 조회 실패: {e}")


@router.patch(
    "/documents/{source}/chunks/{chunk_index}",
    response_model=ChunkUpdateResponse,
    summary="청크 본문 수정(해당 청크만 재임베딩)",
)
def update_document_chunk(source: str, chunk_index: int, body: ChunkUpdateRequest):
    """청크 본문을 고치고 그 청크만 다시 임베딩한다.

    다른 청크는 건드리지 않으므로 문서 재업로드처럼 전체가 다시 쪼개지지 않는다.
    이 핸들러만 async가 아닌 def인 것은 의도적이다 — 임베딩 계산이 수 초 걸려서
    async 안에서 돌리면 그동안 서버 전체가 멈춘다. def면 FastAPI가 스레드풀로 넘긴다.
    """
    try:
        return admin_service.update_chunk(source, chunk_index, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"청크 수정 중 오류: {e}")


@router.delete("/documents/{source}", response_model=DocumentDeleteResponse, summary="문서 삭제")
async def delete_document(source: str):
    try:
        return admin_service.delete_document(source)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 삭제 중 오류: {e}")
