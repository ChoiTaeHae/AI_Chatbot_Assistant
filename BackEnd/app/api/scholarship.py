"""장학금 카탈로그 라우터 — '장학금 둘러보기' 모달용.

채팅 흐름과 별개인 명시적 조회 (학식·졸업 현황과 같은 패턴). RAG 미사용.
"""
import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.school.scholarship_catalog import get_catalog, get_scope_counts, get_kind_counts

router = APIRouter()


@router.get("/scholarships", summary="장학금 카탈로그 (둘러보기 모달)")
async def list_scholarships(
    kind: str = "장학금",
    scope: str = "교내",
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    if kind not in ("장학금", "근로"):
        raise HTTPException(status_code=400, detail="kind는 '장학금' 또는 '근로'만 가능합니다.")
    if scope not in ("교내", "교외"):
        raise HTTPException(status_code=400, detail="scope는 '교내' 또는 '교외'만 가능합니다.")
    try:
        catalog = await get_catalog(db, kind=kind, scope=scope, q=q)
        catalog["counts"] = await get_scope_counts(db, kind)
        catalog["kind_counts"] = await get_kind_counts(db)
        return catalog
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="장학금 정보를 불러오지 못했어요.")
