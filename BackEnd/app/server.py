from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.Database import Base, engine
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.api.admins import router as admins_router
import asyncio
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service
from app.agents.topic_router import topic_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 연결 (async 방식)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("DB 연결 성공")
    except Exception as e:
        print(f"DB 연결 실패 (나중에 연결): {e}")

    # LLM 모델 GPU 로드
    chat_service.load_model()

    # ── 임베딩 인스턴스 공유 ──────────────────────────────
    # rag_service와 topic_router가 동일한 BaaiEmbedding 객체를 사용하도록 연결.
    # 이렇게 하면 BGE-M3 모델이 딱 1번만 로드됨.
    topic_router._embedding = rag_service.embedding

    # topic 프로토타입 벡터 사전 계산 (임베딩 모델 로드 + 6문장 인코딩)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, topic_router.warmup)
        print("topic 라우터 워밍업 완료 (rag_service와 임베딩 공유)")
    
    except Exception as e:
        print(f"topic 라우터 워밍업 실패 (무시): {e}")

    yield
    # 서버 종료 시
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="학교생활지원 AI",
        description="대학교 학생들의 학교생활을 도와주는 AI 챗봇 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 라우터 등록
    app.include_router(auth_router,   prefix="/api/auth",   tags=["인증"])
    app.include_router(chat_router,   prefix="/api",        tags=["챗봇"])
    app.include_router(admins_router, prefix="/api/admins", tags=["관리자"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
