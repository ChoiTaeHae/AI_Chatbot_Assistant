from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.Database import Base, engine
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.api.admins import router as admins_router
from app.api.files import router as files_router
from app.api.campus import router as campus_router
from app.api.graduation import router as graduation_router
from app.api.dining import router as dining_router
from app.api.schedule import router as schedule_router
import asyncio
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.file_service import refresh_available_files
from app.agents.topic_router import topic_router
class _HealthCheckFilter(logging.Filter):
    """uvicorn access 로그에서 /health 폴링을 숨김 (프론트 주기 핑 도배 방지)."""
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn.access args = (client_addr, method, path, http_version, status_code)
        if isinstance(args, tuple) and len(args) >= 3:
            return not str(args[2]).startswith("/health")
        return True

logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

async def _load_topics() -> list[dict]:
    """DB에서 활성 topic 목록 반환."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.models.DB_Table import Topic

    async with AsyncSession(engine) as session:
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


async def _load_schedule_gate() -> None:
    """학사일정 게이트 키워드를 app_config(key=schedule_gate)에서 로드. 없으면 기본값 시딩."""
    from sqlalchemy import select
    from app.core.Database import AsyncSessionLocal   # expire_on_commit=False → commit 후 lazy IO 없음
    from app.models.DB_Table import AppConfig
    from app.agents.agent_graph import set_schedule_gate, DEFAULT_DATE_INTENT, DEFAULT_EVENT_KWS

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(AppConfig).where(AppConfig.key == "schedule_gate"))).scalar_one_or_none()
        if row is None:
            cfg = {"date_intent": DEFAULT_DATE_INTENT, "event_keywords": DEFAULT_EVENT_KWS}
            session.add(AppConfig(key="schedule_gate", value=cfg))
            await session.commit()
        else:
            cfg = dict(row.value or {})
    set_schedule_gate(cfg.get("date_intent"), cfg.get("event_keywords"))


async def _load_search_synonyms() -> None:
    """검색어 딕셔너리를 app_config(key=search_synonyms)에서 로드. 없으면 기본값 시딩."""
    from sqlalchemy import select
    from app.core.Database import AsyncSessionLocal
    from app.models.DB_Table import AppConfig
    from app.services.school.rag_general import set_search_synonyms, DEFAULT_SEARCH_SYNONYMS

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(AppConfig).where(AppConfig.key == "search_synonyms"))).scalar_one_or_none()
        if row is None:
            cfg = dict(DEFAULT_SEARCH_SYNONYMS)
            session.add(AppConfig(key="search_synonyms", value=cfg))
            await session.commit()
        else:
            cfg = dict(row.value or {})
    set_search_synonyms(cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 연결 (async 방식)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # create_all 은 '기존' 테이블을 ALTER 하지 않으므로, 나중에 추가된 컬럼은 여기서
            # 멱등(IF NOT EXISTS)으로 보강한다. nullable 이라 기존 데이터·코드에 무해하고,
            # 공유 DB에 한 번만 적용되면 팀원들도 코드만 받아 재시작하면 동작한다.
            from sqlalchemy import text
            await conn.execute(text(
                "ALTER TABLE chat_message ADD COLUMN IF NOT EXISTS card_meta JSONB"
            ))
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

    # ── 임베딩 인스턴스 공유 ──────────────────────────────
    topic_router._embedding = rag_service.embedding

    # DB에서 활성 topic 로드
    topic_data = await _load_topics()
    print(f"[Server] {len(topic_data)}개 topic 로드 완료")

    # FileService topic 캐시 초기화 → 파일 캐시는 topic 로드 후 갱신
    from app.services.file_service import refresh_topic_cache
    refresh_topic_cache({t["name"]: t["label"] for t in topic_data})
    await refresh_available_files()

    # topic 프로토타입 벡터 사전 계산
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, topic_router.warmup, topic_data)
        print("topic 라우터 워밍업 완료")
    except Exception as e:
        print(f"topic 라우터 워밍업 실패 (무시): {e}")

    # 학사일정 날짜-게이트 키워드 로드 (app_config, 어드민 편집분 반영)
    try:
        await _load_schedule_gate()
    except Exception as e:
        print(f"[Server] 학사일정 게이트 로드 실패 (기본값 사용): {e}")

    # 검색어 딕셔너리 로드 (app_config)
    try:
        await _load_search_synonyms()
    except Exception as e:
        print(f"[Server] 검색어 딕셔너리 로드 실패 (기본값 사용): {e}")

    yield
    # 서버 종료 시
    await engine.dispose()


def create_app() -> FastAPI:
    # API 문서는 기본 비활성(settings.ENABLE_DOCS=false). 인터넷 공개 시 /docs·/redoc·
    # /openapi.json 으로 API 구조 전체가 노출되는 것을 막는다. 세 개를 모두 꺼야 한다
    # (하나만 열려 있어도 openapi 스키마로 전체 구조가 샌다).
    _docs = dict(docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json") if settings.ENABLE_DOCS \
        else dict(docs_url=None, redoc_url=None, openapi_url=None)
    app = FastAPI(
        title="학교생활지원 AI",
        description="대학교 학생들의 학교생활을 도와주는 AI 챗봇 API",
        version="0.1.0",
        lifespan=lifespan,
        **_docs,
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
    app.include_router(graduation_router, prefix="/api",    tags=["졸업"])
    app.include_router(dining_router, prefix="/api",     tags=["학식"])
    app.include_router(schedule_router, prefix="/api",   tags=["학사일정"])
    app.include_router(admins_router, prefix="/api/admins", tags=["관리자"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
