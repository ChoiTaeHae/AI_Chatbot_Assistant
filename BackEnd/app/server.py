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
from app.api.scholarship import router as scholarship_router
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
    """검색어 사전을 search_dictionary 테이블에서 로드해 {term: [official...]}로 재조립.

    테이블이 비어 있으면 최초 1회 시딩한다 — 예전 app_config(key=search_synonyms) blob에
    커스텀 단어가 있으면 그걸 행으로 이관하고(사라지지 않게), 없으면 코드 기본값으로 채운다.
    기존 app_config 행은 안전을 위해 삭제하지 않고 그대로 둔다(추후 수동 정리 가능).
    """
    from sqlalchemy import select
    from app.core.Database import AsyncSessionLocal
    from app.models.DB_Table import SearchDictionary, AppConfig
    from app.services.school.rag_general import set_search_synonyms, DEFAULT_SEARCH_SYNONYMS

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(SearchDictionary).where(SearchDictionary.enabled == True)  # noqa: E712
        )).scalars().all()

        # 표가 비었으면 시딩 (기존 blob 우선 이관 → 없으면 기본값)
        if not rows:
            legacy = (await session.execute(
                select(AppConfig).where(AppConfig.key == "search_synonyms")
            )).scalar_one_or_none()
            source = dict(legacy.value) if (legacy and legacy.value) else dict(DEFAULT_SEARCH_SYNONYMS)
            note = "app_config blob 이관" if (legacy and legacy.value) else "기본값 시딩"
            for term, officials in source.items():
                vals = officials if isinstance(officials, list) else [officials]
                for official in vals:
                    if str(term).strip() and str(official).strip():
                        session.add(SearchDictionary(term=str(term).strip(), official=str(official).strip(), note=note))
            await session.commit()
            rows = (await session.execute(
                select(SearchDictionary).where(SearchDictionary.enabled == True)  # noqa: E712
            )).scalars().all()

        # 행들을 term 기준으로 묶어 dict 재조립
        cfg: dict[str, list[str]] = {}
        for r in rows:
            cfg.setdefault(r.term, [])
            if r.official not in cfg[r.term]:
                cfg[r.term].append(r.official)

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
            # scholarship_file: 파일 1개 → 장학금 여러 개 공유 허용.
            # 옛 '파일당 1개' 유니크(document_file_id) 제거 후 (장학금,파일) 쌍 유니크로 교체(멱등).
            # 기존 데이터는 파일당 1건뿐이라 쌍 유니크를 자동 충족 → 인덱스 생성 실패 없음.
            await conn.execute(text(
                "ALTER TABLE scholarship_file DROP CONSTRAINT IF EXISTS uq_scholarship_file_document"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_scholarship_file_pair "
                "ON scholarship_file (scholarship_id, document_file_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_scholarship_file_document "
                "ON scholarship_file (document_file_id)"
            ))
            # 맞춤 설문 매칭용 요건 컬럼 (전부 nullable/기본 false → 기존 데이터·코드에 무해)
            for _col, _ddl in [
                ("req_region", "VARCHAR(50)"), ("req_region_basis", "VARCHAR(10)"),
                ("req_min_gpa", "DOUBLE PRECISION"), ("req_grade", "VARCHAR(120)"),
                ("req_income", "VARCHAR(20)"), ("req_age_max", "INTEGER"),
                ("req_major_field", "VARCHAR(120)"),
                ("req_multichild", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_foreigner", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_disabled", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_independent", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_veteran", "BOOLEAN NOT NULL DEFAULT false"),
            ]:
                await conn.execute(text(f"ALTER TABLE scholarship_catalog ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
            # 학년·전공계열은 다중선택(콤마 저장)으로 바뀌어 폭을 넓힌다 (기존 VARCHAR(20) → 120, 멱등)
            await conn.execute(text("ALTER TABLE scholarship_catalog ALTER COLUMN req_grade TYPE VARCHAR(120)"))
            await conn.execute(text("ALTER TABLE scholarship_catalog ALTER COLUMN req_major_field TYPE VARCHAR(120)"))
            # 학생 '자동 연동'용 더미 성적/학년/전공계열 컬럼 + 시드
            for _col, _ddl in [("gpa", "DOUBLE PRECISION"), ("grade_year", "INTEGER"), ("major_field", "VARCHAR(20)")]:
                await conn.execute(text(f"ALTER TABLE student ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
            # 아직 값 없는 학생만 결정적(학번 id 기반) 더미로 채움 — 멱등
            await conn.execute(text(
                "UPDATE student SET "
                "gpa = ROUND((3.0 + (id % 16) * 0.1)::numeric, 1), "
                "grade_year = 1 + (id % 4), "
                "major_field = (ARRAY['인문사회','예술체육','이공'])[1 + (id % 3)] "
                "WHERE gpa IS NULL"
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

    # 학과생활 FAQ 인덱스 워밍업 (임베딩 준비된 뒤 — 질문 벡터를 메모리에 상주)
    try:
        from app.services.faq_index import warmup as faq_warmup
        await faq_warmup()
    except Exception as e:
        print(f"[Server] FAQ 인덱스 워밍업 실패 (무시): {e}")

    # 학사일정 날짜-게이트 키워드 로드 (app_config, 어드민 편집분 반영)
    try:
        await _load_schedule_gate()
    except Exception as e:
        print(f"[Server] 학사일정 게이트 로드 실패 (기본값 사용): {e}")

    # 검색어 사전 로드 (search_dictionary 테이블, 최초 1회 시딩/이관)
    try:
        await _load_search_synonyms()
    except Exception as e:
        print(f"[Server] 검색어 사전 로드 실패 (기본값 사용): {e}")

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
    app.include_router(scholarship_router, prefix="/api", tags=["장학금"])
    app.include_router(admins_router, prefix="/api/admins", tags=["관리자"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
