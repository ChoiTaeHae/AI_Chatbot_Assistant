from fastapi import APIRouter

from app.core.config import settings
from app.schemas.admins import SettingsResponse

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse, summary="서비스 설정 조회")
async def get_settings():
    return SettingsResponse(
        dev_mode=settings.DEV_MODE,
        model_path=settings.MODEL_PATH,
        device=settings.DEVICE,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_device=settings.EMBEDDING_DEVICE,
        qdrant_collection=settings.QDRANT_COLLECTION,
        rag_top_k=settings.RAG_TOP_K,
    )
