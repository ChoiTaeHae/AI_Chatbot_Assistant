"""FAQ 관리 API.

FAQ는 '검수된 답변 1개 + 매칭용 질문 변형 N개' 구조다(faq / faq_question). 질문이 인덱스에
매칭되면 LLM을 건너뛰고 답변을 그대로 내보내므로, 잘못 등록하면 교정 여지 없는 확정 오답이
된다 → 변형을 추가할 때는 다른 FAQ와 겹치지 않는지 확인해야 한다(scripts/faq_health_check.py).

모든 변경은 저장 직후 메모리 인덱스를 재적재한다(admin_service._reload_faq_index).
재적재하지 않으면 표만 바뀌고 답변은 그대로여서, 고쳤는데 반영이 안 되는 것처럼 보인다.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.admins import (
    FaqItem,
    FaqCreateRequest,
    FaqUpdateRequest,
    FaqReloadResponse,
)
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/faqs", response_model=list[FaqItem], summary="FAQ 목록 조회")
async def list_faqs(db: AsyncSession = Depends(get_db)):
    return await admin_service.list_faqs(db)


@router.post("/faqs", response_model=FaqItem, summary="FAQ 추가")
async def create_faq(body: FaqCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.create_faq(db, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/faqs/{faq_id}", response_model=FaqItem, summary="FAQ 수정")
async def update_faq(faq_id: int, body: FaqUpdateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await admin_service.update_faq(db, faq_id, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/faqs/{faq_id}", summary="FAQ 삭제")
async def delete_faq(faq_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await admin_service.delete_faq(db, faq_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": faq_id}


@router.post("/faq/reload", response_model=FaqReloadResponse, summary="FAQ 인덱스 수동 재적재")
async def reload_faq_index():
    """표를 SQL로 직접 고쳤을 때처럼, 이 API를 거치지 않은 변경을 반영하는 용도.
    화면에서 저장하면 자동으로 재적재되므로 평소에는 쓸 일이 없다."""
    from app.services import faq_index

    try:
        await faq_index.warmup()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAQ 인덱스 재적재 실패: {e}")
    # 모듈 속성으로 읽는다 — from ... import _index 로 받으면 재적재 전 리스트가 박힌다
    return FaqReloadResponse(count=len(faq_index._index))
