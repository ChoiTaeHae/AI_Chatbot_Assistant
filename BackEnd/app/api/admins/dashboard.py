from fastapi import APIRouter, HTTPException

from app.services.rag_service import rag_service
from app.services.chat_service import chat_service
from app.core.config import settings
from app.schemas.admins import DashboardResponse

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse, summary="대시보드 요약 정보")
async def get_dashboard():
    try:
        sources = rag_service.vector_store.list_sources()
        total_docs = len(sources)
        total_chunks = sum(s["chunks"] for s in sources)
    except Exception as e:
        print(f"[DASHBOARD] Qdrant 조회 실패: {e}")
        total_docs = 0
        total_chunks = 0

    model_loaded = (chat_service.model is not None) or settings.DEV_MODE

    return DashboardResponse(
        total_documents=total_docs,
        total_chunks=total_chunks,
        model_status="loaded" if model_loaded else "not_loaded",
        dev_mode=settings.DEV_MODE,
        model_path=settings.MODEL_PATH,
    )
