from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.services.admin_service import admin_service
from app.schemas.admins import ChatSessionListResponse, ChatSessionDetailResponse, AdminFeedbackRequest, FeedbackItem

router = APIRouter()


@router.get("/chat-sessions", response_model=ChatSessionListResponse, summary="채팅 세션 목록 조회")
async def list_chat_sessions(
    search: str = Query("", description="이름·학번 검색"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_service.get_chat_sessions(db, search=search, page=page, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채팅 세션 조회 실패: {e}")


@router.get("/chat-sessions/{session_id}/messages", response_model=ChatSessionDetailResponse, summary="채팅 세션 메시지 조회")
async def get_session_messages(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_service.get_session_messages(db, session_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"메시지 조회 실패: {e}")


@router.post("/chat-sessions/{session_id}/messages/{message_id}/feedback", response_model=FeedbackItem, summary="메시지 피드백 작성/수정")
async def upsert_message_feedback(
    session_id: int,
    message_id: int,
    req: AdminFeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_service.upsert_feedback(db, message_id, req)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"피드백 저장 실패: {e}")
