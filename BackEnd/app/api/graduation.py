"""
졸업 관련 라우터 — 개인 졸업 현황 조회 (명시적 액션)

채팅의 졸업 질문(규정)은 chat 흐름에서 RAG로 처리한다.
개인 이수현황·부족학점은 이 엔드포인트로 분리 — 로그인 학생 본인 학과 기준.
(다른 학과 요건을 물었을 때 본인 개인현황이 섞여 나오는 환각 방지)
"""
import traceback

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.services.school.graduation import graduation_service

router = APIRouter()


@router.get("/graduation/status", summary="내 졸업 현황 조회 (로그인 학생 본인)")
async def graduation_status(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        answer = await graduation_service.get_status_answer(current_user.id, db)
        return {"answer": answer}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"졸업 현황 조회 오류: {str(e)}")


@router.get("/graduation/report", summary="학점 진행률 (사이드바 위젯 · 학점만)")
async def graduation_report(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    # 학생이 아니면(관리자 등) 학점 데이터 없음 → 위젯 숨김 신호
    if current_user.role != "student":
        return {"available": False, "reason": "not_student"}
    try:
        data = await graduation_service.get_status_report(current_user.id, db)
        if data.get("available"):
            data["student_no"] = current_user.student_no
        return data
    except Exception:
        traceback.print_exc()
        return {"available": False}
