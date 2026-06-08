import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.rag.ingest import ingest_file
from app.services.rag_service import rag_service
from app.schemas.admin import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentListItem,
    DocumentDeleteResponse,
)

router = APIRouter()

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".hwp"}


@router.post("/documents/upload", response_model=DocumentUploadResponse, summary="문서 업로드 및 RAG 등록")
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form(None),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    # 임시 파일로 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        source_name = source or Path(file.filename).stem
        chunk_count = ingest_file(
            file_path=tmp_path,
            source=source_name,
            service=rag_service,
        )

        if chunk_count == 0:
            raise HTTPException(status_code=422, detail="문서에서 텍스트를 추출할 수 없습니다.")

        return DocumentUploadResponse(
            success=True,
            source=source_name,
            file_name=file.filename,
            chunks=chunk_count,
            message=f"'{file.filename}' 업로드 완료 ({chunk_count}개 청크 생성)",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 처리 중 오류: {str(e)}")
    finally:
        tmp_path.unlink(missing_ok=True)


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
