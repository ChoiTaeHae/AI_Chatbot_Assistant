from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.Database import Base, engine
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.api.admins import router as admins_router
from app.api.files import router as files_router
from app.api.campus import router as campus_router
import asyncio
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.file_service import refresh_available_files
from app.agents.topic_router import topic_router


async def _seed_and_load_topics() -> list[dict]:
    """Topic 테이블 시드 삽입 후 활성 topic 목록 반환."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.models.DB_Table import Topic
    from app.core.topics import TOPIC_SEED

    async with AsyncSession(engine) as session:
        result = await session.execute(select(Topic))
        existing_names = {t.name for t in result.scalars().all()}

        for seed in TOPIC_SEED:
            if seed["name"] not in existing_names:
                session.add(Topic(
                    name=seed["name"],
                    label=seed["label"],
                    handler_type=seed["handler_type"],
                    sentences=seed.get("sentences", []),
                    description=seed.get("description"),
                    is_system=seed.get("is_system", False),
                    is_active=True,
                ))

        await session.commit()

        result = await session.execute(
            select(Topic).where(Topic.is_active == True)
        )
        topics = result.scalars().all()
        return [
            {
                "name": t.name,
                "label": t.label,
                "handler_type": t.handler_type,
                "sentences": t.sentences or [],
            }
            for t in topics
        ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 연결 (async 방식)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("DB 연결 성공")
    except Exception as e:
        print(f"DB 연결 실패 (나중에 연결): {e}")

    # Windows TxF 스레드 오류 방지 — 스레드 전에 lazy import 모두 실행
    try:
        import importlib, pkgutil

        # fsspec 전체 구현체 스캔
        import fsspec
        import fsspec.implementations as _fi
        for _, modname, _ in pkgutil.walk_packages(_fi.__path__, prefix='fsspec.implementations.'):
            try: importlib.import_module(modname)
            except Exception: pass
        fsspec.filesystem('file')

        # huggingface_hub 전체 서브모듈 스캔
        import huggingface_hub as _hf
        for _, modname, _ in pkgutil.walk_packages(_hf.__path__, prefix='huggingface_hub.'):
            try: importlib.import_module(modname)
            except Exception: pass

        print("[Server] fsspec/huggingface_hub 사전 초기화 완료")
    except Exception as e:
        print(f"[Server] 사전 초기화 실패 (무시): {e}")

    # LLM 모델 GPU 로드
    llm_service.load_model()

    # 다운로드 파일 캐시 초기화
    refresh_available_files()

    # ── 임베딩 인스턴스 공유 ──────────────────────────────
    topic_router._embedding = rag_service.embedding

    # Topic 시드 삽입 + 활성 topic 로드
    try:
        topic_data = await _seed_and_load_topics()
        print(f"[Server] {len(topic_data)}개 topic 로드 완료")
    except Exception as e:
        print(f"[Server] topic DB 로드 실패 — TOPIC_SEED 사용: {e}")
        from app.core.topics import TOPIC_SEED
        topic_data = [
            {"name": t["name"], "label": t["label"],
             "handler_type": t["handler_type"], "sentences": t.get("sentences", [])}
            for t in TOPIC_SEED
        ]

    # FileService topic 캐시 초기화
    from app.services.file_service import refresh_topic_cache
    refresh_topic_cache({t["name"]: t["label"] for t in topic_data})

    # topic 프로토타입 벡터 사전 계산
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, topic_router.warmup, topic_data)
        print("topic 라우터 워밍업 완료")
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
    app.include_router(files_router,  prefix="/api",        tags=["파일"])
    app.include_router(campus_router, prefix="/api",        tags=["캠퍼스"])
    app.include_router(admins_router, prefix="/api/admins", tags=["관리자"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
