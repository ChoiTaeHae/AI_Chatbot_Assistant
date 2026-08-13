"""FAQ 관리 API.

FAQ는 '검수된 답변 1개 + 매칭용 질문 변형 N개' 구조다(faq / faq_question). 질문이 인덱스에
매칭되면 LLM을 건너뛰고 답변을 그대로 내보내므로, 잘못 등록하면 교정 여지 없는 확정 오답이
된다 → 변형을 추가할 때는 다른 FAQ와 겹치지 않는지 확인해야 한다(scripts/faq_health_check.py).

모든 변경은 저장 직후 메모리 인덱스를 재적재한다(admin_service._reload_faq_index).
재적재하지 않으면 표만 바뀌고 답변은 그대로여서, 고쳤는데 반영이 안 되는 것처럼 보인다.

이 라우터는 두 가지를 담당한다.
  · /faqs …            검수된 FAQ의 CRUD (admin_service)
  · /faq/unanswered …  답하지 못한 질문 → 답변 작성 → FAQ 전환 (faq_service)
둘을 한 라우터에 두는 이유 — 관리자 입장에서는 같은 화면의 앞뒤 단계다.
미답변 목록에서 답변을 쓰면 그대로 FAQ가 되므로, 경로를 나누면 오히려 흐름이 끊긴다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.admins import (
    FaqItem,
    FaqCreateRequest,
    FaqUpdateRequest,
    FaqReloadResponse,
    UnansweredAnswerRequest,
    UnansweredAnswerResponse,
    UnansweredCountResponse,
    UnansweredItem,
    UnansweredStatusRequest,
)
from app.services import faq_service
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


# ── 미답변 질문 → FAQ 전환 ──────────────────────────────────────
# 상태: pending(확인 대기) / answered(FAQ 전환됨) / ignored(관리자가 제외)
#       filtered(LLM 선별에서 학사 무관·부적절로 걸러짐 — 지우지 않고 남긴다)


@router.get("/faq/unanswered", response_model=list[UnansweredItem],
            summary="미답변 질문 목록")
async def list_unanswered(
    status: str = Query("pending", description="pending | answered | ignored | filtered"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """많이 물어본 것부터 정렬해 돌려준다 — 무엇을 먼저 답할지가 목록의 핵심 정보다."""
    return await faq_service.list_questions(db, status=status, limit=limit)


@router.get("/faq/unanswered/count", response_model=UnansweredCountResponse,
            summary="미답변 질문 대기 건수")
async def count_unanswered(db: AsyncSession = Depends(get_db)):
    """관리자 화면 배지용."""
    return UnansweredCountResponse(pending=await faq_service.count_pending(db))


@router.patch("/faq/unanswered/{row_id}", summary="미답변 질문 상태 변경")
async def update_unanswered_status(
    row_id: int, body: UnansweredStatusRequest, db: AsyncSession = Depends(get_db)
):
    try:
        ok = await faq_service.set_status(db, row_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="미답변 질문을 찾을 수 없습니다.")
    return {"ok": True, "status": body.status}


@router.post("/faq/unanswered/{row_id}/answer", response_model=UnansweredAnswerResponse,
             summary="답변 작성 → FAQ 등록")
async def answer_unanswered(
    row_id: int, body: UnansweredAnswerRequest, db: AsyncSession = Depends(get_db)
):
    """답변을 FAQ로 만든다.

    커밋과 인덱스 재적재는 서비스가 끝낸다(faq_service의 트랜잭션 규칙 참고).
    여기서는 입력 검증과 예외→상태코드 변환만 한다.
    """
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="답변 내용을 입력하세요.")
    try:
        result = await faq_service.answer_to_faq(
            db, row_id, body.answer.strip(), body.extra_questions
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # 이미 답변된 질문 — 저장 버튼 연타나 두 관리자의 동시 처리.
        # 409를 쓰는 이유는 '요청이 잘못됐다'(400)가 아니라 '지금 상태와 맞지 않는다'이기
        # 때문이다. 화면은 이 응답을 받으면 목록을 새로 읽어 이미 처리된 것을 보여 주면 된다.
        raise HTTPException(status_code=409, detail=str(e))

    return UnansweredAnswerResponse(**result)
