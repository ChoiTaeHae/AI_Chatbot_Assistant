"""마이페이지 라우터 — 로그인한 학생 본인의 정보 조회/수정.

모든 엔드포인트가 get_current_user에 의존한다. 이 의존성이 Bearer 토큰 서명·만료를 검증하고
로그아웃된(블랙리스트) 토큰을 막은 뒤 Student를 넘겨주므로, 라우터는 '본인 확인'을 따로 하지
않는다. 대상 학생을 경로 파라미터로 받지 않고 토큰의 학생만 다루는 것도 같은 이유다 —
남의 id를 넣어 다른 사람 정보를 고치는 경로 자체가 없다.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.Database import get_db
from app.core.deps import get_current_user
from app.models.DB_Table import Student
from app.schemas.me import (
    MeResponse, MeUpdateRequest, PasswordChangeRequest, DeptOption,
    CourseRow, CoursePreviewResponse, CourseCommitRequest, CourseCommitResponse, SavedCourse,
)
from app.services.me_service import me_service
from app.services.student_course_service import student_course_service

router = APIRouter()

# 업로드 상한 — 성적표 엑셀은 수십 KB라 넉넉하다. 큰 파일로 메모리를 밀어내지 못하게 막는다.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.get("/me", response_model=MeResponse, summary="내 정보 조회")
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    return await me_service.get_me(db, current_user)


@router.get("/me/departments", response_model=list[DeptOption], summary="학과 선택 목록")
async def list_departments(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    return await me_service.list_departments(db)


@router.patch("/me", response_model=MeResponse, summary="내 정보 수정")
async def update_me(
    body: MeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await me_service.update_me(db, current_user.id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/me/password", summary="비밀번호 변경")
async def change_password(
    body: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        await me_service.change_password(db, current_user.id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"changed": True}


# ── 수강 이력 ──────────────────────────────────────────────
# 업로드는 '미리보기 → 확정' 2단계다. 성적표는 학생에게 민감한 데이터라, 형식이 다르거나
# 엉뚱한 파일을 올렸을 때 곧바로 DB에 들어가면 되돌리기 번거롭다. 확인 후 저장하게 한다.

@router.get("/me/courses", response_model=list[SavedCourse], summary="내 수강 이력")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    return await student_course_service.list_courses(db, current_user.id)


@router.post("/me/courses/preview", response_model=CoursePreviewResponse,
             summary="성적 엑셀 미리보기 (저장하지 않음)")
async def preview_courses(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="xlsx 파일만 올릴 수 있습니다.")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다 (5MB 이하).")
    try:
        return await student_course_service.preview_excel(db, current_user.id, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/me/courses/commit", response_model=CourseCommitResponse,
             summary="미리보기 결과 저장 (병합)")
async def commit_courses(
    body: CourseCommitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await student_course_service.merge_courses(
            db, current_user.id, [r.model_dump() for r in body.rows])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/me/courses", summary="수강 과목 직접 추가")
async def add_course(
    body: CourseRow,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await student_course_service.add_course(db, current_user.id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/me/courses/{row_id}", summary="수강 과목 삭제")
async def delete_course(
    row_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await student_course_service.delete_course(db, current_user.id, row_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
