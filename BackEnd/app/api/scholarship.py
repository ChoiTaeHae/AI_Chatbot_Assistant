"""장학금 카탈로그 라우터 — '장학금 둘러보기' 모달용.

채팅 흐름과 별개인 명시적 조회 (학식·졸업 현황과 같은 패턴). RAG 미사용.
"""
import traceback

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.school.scholarship_catalog import (
    get_catalog, get_scope_counts, get_kind_counts, match_scholarships,
)

router = APIRouter()


class MatchRequest(BaseModel):
    """맞춤 장학금 설문 답. 성적·학년·전공은 서버가 학생 레코드(더미)에서 자동 연동."""
    self_region: str | None = None       # 본인 거주 지역
    parent_region: str | None = None     # 부모님 거주 지역
    income: str | None = None            # '기초'|'차상위'|'중위100'|'중위200'|None
    interests: list[str] = []            # 관심 유형(카테고리) — 우선 정렬용
    age: int | None = None
    multichild: bool = False             # 다자녀 가정
    foreigner: bool = False              # 외국인/유학생
    disabled: bool = False               # 장애
    independent: bool = False            # 자취/독립 거주
    veteran: bool = False                # 보훈·국가유공자(후손)


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
    if scope not in ("교내", "교외", "전체"):
        raise HTTPException(status_code=400, detail="scope는 '교내'·'교외'·'전체'만 가능합니다.")
    try:
        catalog = await get_catalog(db, kind=kind, scope=scope, q=q)
        catalog["counts"] = await get_scope_counts(db, kind)
        catalog["kind_counts"] = await get_kind_counts(db)
        return catalog
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="장학금 정보를 불러오지 못했어요.")


@router.post("/scholarships/match", summary="맞춤 장학금 필터 (설문)")
async def match(
    body: MatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    """설문 답 + 학생 더미 성적/학년/전공으로 맞는 장학금을 필터해서 반환."""
    try:
        result = await match_scholarships(
            db,
            body.model_dump(),
            gpa=getattr(current_user, "gpa", None),
            grade_year=getattr(current_user, "grade_year", None),
            major_field=getattr(current_user, "major_field", None),
        )
        # 설문 모달의 '연동됨' 표시용 — 자동으로 가져온 학생 프로필
        result["profile"] = {
            "name": current_user.name,
            "gpa": getattr(current_user, "gpa", None),
            "grade_year": getattr(current_user, "grade_year", None),
            "major_field": getattr(current_user, "major_field", None),
        }
        return result
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail="맞춤 장학금 조회에 실패했어요.")
