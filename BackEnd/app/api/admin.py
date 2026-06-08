import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks

from app.rag.ingest import ingest_file
from app.services.rag_service import rag_service
from app.schemas.admin import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentListItem,
    DocumentDeleteResponse,
)

router = APIRouter()

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}

# 업로드 작업 상태 저장 (간단한 메모리 딕셔너리)
upload_jobs: dict[str, dict] = {}

# 백그라운드 처리용 전용 스레드풀
_ingest_executor = ThreadPoolExecutor(max_workers=1)


def _run_ingest(job_id: str, tmp_path: Path, source_name: str, file_name: str, topic: str | None = None):
    """백그라운드에서 실행되는 ingest 작업"""
    try:
        upload_jobs[job_id]["status"] = "processing"
        chunk_count = ingest_file(
            file_path=tmp_path,
            source=source_name,
            service=rag_service,
            topic=topic,
        )
        if chunk_count == 0:
            upload_jobs[job_id] = {
                "status": "error",
                "message": "문서에서 텍스트를 추출할 수 없습니다.",
            }
        else:
            upload_jobs[job_id] = {
                "status": "done",
                "source": source_name,
                "file_name": file_name,
                "chunks": chunk_count,
                "message": f"'{file_name}' 처리 완료 ({chunk_count}개 청크 생성)",
            }
        print(f"[INGEST] 완료: {source_name} ({chunk_count} chunks)")
    except Exception as e:
        upload_jobs[job_id] = {"status": "error", "message": str(e)}
        print(f"[INGEST] 오류: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


VALID_TOPICS = {"graduation", "schedule", "leave", "campus", "scholarship", "general"}


@router.post("/documents/upload", summary="문서 업로드 및 RAG 등록 (백그라운드 처리)")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Form(None),
    topic: str = Form(None),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    if topic and topic not in VALID_TOPICS:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 주제입니다. 가능한 값: {', '.join(sorted(VALID_TOPICS))}"
        )

    # 임시 파일 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    source_name = source or Path(file.filename).stem
    job_id = f"{source_name}_{tmp_path.stem}"

    upload_jobs[job_id] = {"status": "queued", "source": source_name, "topic": topic, "file_name": file.filename}

    # 백그라운드에서 ingest 실행
    background_tasks.add_task(
        _ingest_executor.submit,
        _run_ingest, job_id, tmp_path, source_name, file.filename, topic
    )

    return {
        "success": True,
        "job_id": job_id,
        "source": source_name,
        "topic": topic,
        "file_name": file.filename,
        "message": f"'{file.filename}' 업로드 완료. 백그라운드에서 RAG 처리 중입니다.",
    }


@router.get("/documents/status/{job_id}", summary="업로드 처리 상태 확인")
async def get_upload_status(job_id: str):
    job = upload_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


@router.get("/documents", response_model=DocumentListResponse, summary="RAG 문서 목록 조회")
async def list_documents():
    try:
        sources = rag_service.vector_store.list_sources()
        items = [DocumentListItem(**s) for s in sources]
        return DocumentListResponse(documents=items, total=len(items))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(e)}")


@router.delete("/documents/{source}", response_model=DocumentDeleteResponse, summary="문서 삭제")
async def delete_document(source: str):
    try:
        deleted = rag_service.vector_store.delete_by_source(source)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"'{source}' 문서를 찾을 수 없습니다.")
        return DocumentDeleteResponse(
            success=True,
            source=source,
            message=f"'{source}' 문서 삭제 완료 ({deleted}개 청크 삭제)",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 삭제 중 오류: {str(e)}")
