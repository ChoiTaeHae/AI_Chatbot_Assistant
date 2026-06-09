from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.Database import get_db
from app.models.DB_Table import Student, Department, Course
from app.schemas.admins import StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse, summary="사용 통계 조회")
async def get_stats(db: AsyncSession = Depends(get_db)):
    try:
        student_count = await db.scalar(select(func.count(Student.id)))
        dept_count    = await db.scalar(select(func.count(Department.id)))
        course_count  = await db.scalar(select(func.count(Course.code)))
        admin_count   = await db.scalar(
            select(func.count(Student.id)).where(Student.role == "admin")
        )
        return StatsResponse(
            total_students=student_count or 0,
            total_departments=dept_count or 0,
            total_courses=course_count or 0,
            total_admins=admin_count or 0,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")
