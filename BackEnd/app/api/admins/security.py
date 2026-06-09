from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.Database import get_db
from app.models.DB_Table import Student, Department
from app.schemas.admins import UserItem, UserListResponse, RoleUpdate

router = APIRouter()

VALID_ROLES = {"student", "admin"}


@router.get("/users", response_model=UserListResponse, summary="사용자 목록 조회")
async def get_users(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(Student, Department.name)
            .outerjoin(Department, Student.dept_id == Department.id)
        )
        rows = result.all()
        users = [
            UserItem(
                id=s.id,
                student_no=s.student_no,
                name=s.name,
                role=s.role,
                department=dept_name or "-",
            )
            for s, dept_name in rows
        ]
        return UserListResponse(users=users, total=len(users))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 실패: {str(e)}")


@router.patch("/users/{user_id}/role", response_model=UserItem, summary="사용자 권한 변경")
async def update_user_role(user_id: int, body: RoleUpdate, db: AsyncSession = Depends(get_db)):
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role은 'student' 또는 'admin'만 가능합니다.")

    result = await db.execute(
        select(Student, Department.name)
        .outerjoin(Department, Student.dept_id == Department.id)
        .where(Student.id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    student, dept_name = row
    student.role = body.role
    await db.commit()
    await db.refresh(student)   # commit 후 만료된 속성 재로드

    return UserItem(
        id=student.id,
        student_no=student.student_no,
        name=student.name,
        role=student.role,
        department=dept_name or "-",
    )
