from fastapi import APIRouter

from app.api.admins.rag import router as rag_router
from app.api.admins.dashboard import router as dashboard_router
from app.api.admins.usagedata import router as usagedata_router
from app.api.admins.service import router as service_router
from app.api.admins.security import router as security_router

router = APIRouter()
router.include_router(rag_router)
router.include_router(dashboard_router)
router.include_router(usagedata_router)
router.include_router(service_router)
router.include_router(security_router)
