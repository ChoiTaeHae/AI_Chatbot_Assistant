from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.Database import Base, engine
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router

from app.api.campus import router as campus_router
from app.services.chat_service import chat_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 연결 (실패해도 서버는 계속 실행)
    try:
        Base.metadata.create_all(bind=engine)
        print("DB 연결 성공")
    except Exception as e:
        print(f"DB 연결 실패 (나중에 연결): {e}")

    # LLM 모델 GPU 로드
    chat_service.load_model()
    yield
    # 서버 종료 시


def create_app() -> FastAPI:
    app = FastAPI(
        title="학교생활지원 AI",
        description="대학교 학생들의 학교생활을 도와주는 AI 챗봇 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.FRONTEND_ORIGINS.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 라우터 등록
    app.include_router(auth_router, prefix="/api/auth", tags=["인증"])
    app.include_router(chat_router, prefix="/api",      tags=["챗봇"])
    app.include_router(campus_router, prefix="/api/campus", tags=["학교 위치 안내"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
