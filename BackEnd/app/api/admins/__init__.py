from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.api.admins.rag import router as rag_router
from app.api.admins.faq import router as faq_router
from app.api.admins.dashboard import router as dashboard_router
from app.api.admins.usagedata import router as usagedata_router
from app.api.admins.service import router as service_router
from app.api.admins.security import router as security_router
from app.api.admins.files import router as files_router
from app.api.admins.scholarships import router as scholarships_router
from app.api.admins.departments import router as departments_router
from app.api.admins.chats import router as chats_router

# 모든 /api/admins/* 라우터에 관리자 인증 적용
router = APIRouter(dependencies=[Depends(require_admin)])
router.include_router(rag_router)
router.include_router(faq_router)
router.include_router(dashboard_router)
router.include_router(usagedata_router)
router.include_router(service_router)
router.include_router(security_router)
router.include_router(files_router)
router.include_router(scholarships_router)
router.include_router(departments_router)
router.include_router(chats_router)
