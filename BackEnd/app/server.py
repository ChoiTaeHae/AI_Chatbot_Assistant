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
from app.api.me import router as me_router
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


async def _seed_my_grades_topic() -> None:
    """'내 성적 조회' 라우팅 topic을 없으면 만든다(멱등).

    이 topic엔 Qdrant 문서가 없다 — 답은 학생의 수강 이력(student_course)에서 나온다.
    라우터에 등록해 두는 이유는 두 가지다.
      · 키워드 fast-path가 놓친 표현('나 성적 어때?')을 임베딩이 받아 준다.
      · 후속 질문('2학기는?')이 이전 topic 유지(stickiness)로 같은 핸들러에 남는다.
    문장은 어드민 'topic 관리'에서 편집할 수 있고, 여기 기본값은 최초 1회만 쓰인다.
    """
    from sqlalchemy import select
    from app.core.Database import AsyncSessionLocal
    from app.models.DB_Table import Topic

    # 문장은 전부 '성적표를 달라'는 쪽으로 고정한다. '내 학점 얼마나 들었어?'처럼 학점만
    # 말하는 문장은 넣지 않는다 — graduation의 '내 졸업학점 얼마나 남았어?'와 임베딩이 겹쳐
    # 졸업 잔여학점 질문을 이 토픽이 가로챈다(키워드 게이트에서 실제로 적발된 충돌).
    sentences = [
        "내 성적 알려줘",
        "내 성적표 보여줘",
        "2학년 1학기 과목별 성적 알려줘",
        "1학년 2학기에 뭐 들었는지 알려줘",
        "이번 학기 성적 보여줘",
        "지난 학기 평점 얼마야?",
        "제 평점평균이 몇 점인가요?",
        "학기별 평점 정리해서 보여줘",
        "학기별 성적 정리해서 보여줘",
        "3학년 1학기 성적표 보여줘",
        "2025년 2학기 성적 알려줘",
        "내가 A+ 받은 과목 뭐야?",
        "전공 과목 성적 알려줘",
        "자료구조 성적 몇 점이야?",
        "내 수강 이력 보여줘",
        "내가 들은 과목 목록 보여줘",
        "학년별로 평점 어떻게 되는지 알려줘",
        "여름학기에 들은 과목 알려줘",
    ]

    async with AsyncSessionLocal() as session:
        exists = (await session.execute(
            select(Topic).where(Topic.name == "my_grades"))).scalar_one_or_none()
        if exists:
            return
        session.add(Topic(
            name="my_grades", label="내 성적 조회", handler_type="my_grades",
            sentences=sentences, is_system=True, is_active=True,
            description="본인 수강 이력(student_course)으로 학기별 과목·등급·평점을 답한다. RAG 미사용.",
        ))
        await session.commit()
        print("[Server] topic 'my_grades' 시딩 완료")


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
                ("req_departments", "VARCHAR(500)"),
                ("req_multichild", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_foreigner", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_disabled", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_independent", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_veteran", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_excellent", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_flags_preferential", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_multicultural", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_defector", "BOOLEAN NOT NULL DEFAULT false"),
                ("req_age_min", "INTEGER"),
                ("display_order", "INTEGER"),
            ]:
                await conn.execute(text(f"ALTER TABLE scholarship_catalog ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
            # 학년·전공계열은 다중선택(콤마 저장)으로 바뀌어 폭을 넓힌다 (기존 VARCHAR(20) → 120, 멱등)
            await conn.execute(text("ALTER TABLE scholarship_catalog ALTER COLUMN req_grade TYPE VARCHAR(120)"))
            await conn.execute(text("ALTER TABLE scholarship_catalog ALTER COLUMN req_major_field TYPE VARCHAR(120)"))
            # 지원 조건은 여러 줄(줄바꿈 구분)로 저장돼 300자를 넘을 수 있다 → TEXT로 확장 (멱등)
            await conn.execute(text("ALTER TABLE scholarship_catalog ALTER COLUMN eligibility TYPE TEXT"))
            # 학생 '자동 연동'용 더미 성적/학년/전공계열 컬럼 + 시드
            for _col, _ddl in [("gpa", "DOUBLE PRECISION"), ("grade_year", "INTEGER"), ("major_field", "VARCHAR(20)")]:
                await conn.execute(text(f"ALTER TABLE student ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
            # 아직 값 없는 학생만 결정적(학번 id 기반) 더미로 채움 — 멱등.
            #
            # 학점(gpa)은 더 이상 더미로 채우지 않는다
            #   마이페이지의 수강 이력 업로드가 생기면서 gpa는 student_course에서 계산되는
            #   실측값이 됐다. 더미를 함께 두면 '수업 0개인데 평점 3.5' 같은 모순이 생기고
            #   (관리자 계정에도 학점이 붙었다), 학생이 과목을 모두 지워 gpa가 NULL이 되면
            #   다음 기동 때 더미가 되살아나 지운 값이 돌아오는 문제까지 있었다.
            #   장학금 매칭은 설문 입력값을 쓰고 졸업 현황은 student_course로 계산하므로,
            #   더미를 없애도 달라지는 판정은 없다(표시만 '아직 없음'이 된다).
            #
            # 학년·전공계열은 아직 대체 수단이 없어 남긴다(마이페이지에서 학생이 교정 가능).
            # 판정 기준을 gpa에서 grade_year로 옮긴다 — gpa가 더 이상 '시딩 여부' 표식이 아니다.
            await conn.execute(text(
                "UPDATE student SET grade_year = 1 + (id % 4) WHERE grade_year IS NULL"))
            # 전공계열은 학번 id가 아니라 '소속 학과'에서 가져온다. id % 3 더미를 쓰던 때는
            # 컴퓨터·소프트웨어전공 학생에게 '인문사회'가 붙는 식으로 학과와 어긋났다.
            await conn.execute(text(
                "UPDATE student s SET major_field = d.major_field FROM department d "
                "WHERE d.id = s.dept_id AND d.major_field IS NOT NULL "
                "AND s.major_field IS NULL"))
            # 수강 이력이 없는 학생의 학점은 비운다 — 옛 더미 정리이자 앞으로도 유지할 불변식
            # ('과목이 없으면 평점도 없다'). 이력이 있는 학생의 계산값은 건드리지 않는다.
            await conn.execute(text(
                "UPDATE student SET gpa = NULL "
                "WHERE gpa IS NOT NULL AND id NOT IN "
                "(SELECT student_id FROM student_course WHERE student_id IS NOT NULL)"
            ))
            # ── 값 범위 제약(CHECK) ──────────────────────────────────
            # 지금까지 값 검증은 Pydantic(API 입구)에만 있었다. SQL로 직접 넣거나 스크립트로
            # 넣으면 막을 것이 없어 DB가 마지막 방어선 역할을 못 했다.
            #
            # course.category가 특히 중요하다 — 졸업 학점 집계가 문자열 정확 일치에 의존한다.
            #   earned_major = passed.get("전공필수") + passed.get("전공선택")
            # '전공 필수'(공백 하나)처럼 어긋난 값이 들어가면 오류 없이 그 과목 학점이 0으로
            # 계산된다. 학생은 학점이 왜 모자란지 알 수 없다 — 조용히 틀리는 유일한 경우다.
            #
            # ADD CONSTRAINT에는 IF NOT EXISTS가 없어 DO 블록으로 중복을 삼킨다(멱등).
            # 제약을 어기는 데이터가 이미 있으면 ALTER 자체가 실패하므로, 실패해도 기동을
            # 막지 않도록 개별로 감싼다(로그만 남기고 계속 — 기존 데이터 정리는 별도 작업).
            _CHECKS = [
                ("course", "ck_course_category",
                 "category IN ('전공필수','전공선택','교양필수','교양선택','일반','트랙')"),
                ("student", "ck_student_gpa",
                 "gpa IS NULL OR (gpa >= 0 AND gpa <= 4.5)"),
                ("student", "ck_student_grade_year",
                 "grade_year IS NULL OR (grade_year >= 1 AND grade_year <= 4)"),
                ("student", "ck_student_role",
                 "role IN ('student','admin')"),
                ("student", "ck_student_major_field",
                 "major_field IS NULL OR major_field IN ('인문사회','예술체육','이공','의학계열')"),
                ("department", "ck_department_major_field",
                 "major_field IS NULL OR major_field IN ('인문사회','예술체육','이공','의학계열')"),
            ]
            for _tbl, _name, _expr in _CHECKS:
                try:
                    await conn.execute(text(
                        f"DO $$ BEGIN "
                        f"ALTER TABLE {_tbl} ADD CONSTRAINT {_name} CHECK ({_expr}); "
                        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"))
                except Exception as _e:
                    print(f"[Server] CHECK 제약 {_name} 추가 실패(무시): {_e}")

            # 옛 id % 3 더미로 박힌 전공계열을 학과 기준으로 바로잡는다.
            #   조건에 '값이 아직 더미 공식과 똑같은 행'만 넣는 이유
            #   학생이 마이페이지에서 직접 고른 값(학과 규칙이 못 맞추는 예외)을 기동할 때마다
            #   되돌려버리면 안 된다. 더미 공식과 일치하는 행은 '아무도 손대지 않은 값'이므로
            #   덮어써도 잃을 게 없다. 우연히 일치했더라도 학과에서 온 값이 더 정확하다.
            await conn.execute(text(
                "UPDATE student s SET major_field = d.major_field FROM department d "
                "WHERE d.id = s.dept_id AND d.major_field IS NOT NULL "
                "AND s.major_field IS DISTINCT FROM d.major_field "
                "AND s.major_field = (ARRAY['인문사회','예술체육','이공'])[1 + (s.id % 3)]"
            ))

            # 학과별 전공계열 — 마이페이지에서 학과를 고르면 계열을 자동으로 채우기 위한 값.
            # 학생의 major_field는 원래 id % 3 더미라 장학금 매칭이 실제 전공과 무관했다.
            # 학과명 키워드로 1차 분류하고(멱등, NULL인 행만), 예외는 학생이 마이페이지에서
            # 직접 고칠 수 있게 둔다. 계열 값은 scholarship_catalog.req_major_field와 같은
            # 어휘를 쓴다(인문사회 / 예술체육 / 이공 / 의학계열).
            await conn.execute(text(
                "ALTER TABLE department ADD COLUMN IF NOT EXISTS major_field VARCHAR(20)"))
            # 순서가 중요하다 — 앞 규칙이 이긴다.
            #   '보건의료경영'·'AI경영'·'철도경영'은 경영(인문사회)이 주전공이므로 경영을 먼저 본다.
            _DEPT_FIELD_RULES = [
                ("인문사회", ["경영", "경제", "복지", "교육", "관광", "호텔", "무역", "국제"]),
                ("의학계열", ["간호", "물리치료", "작업치료", "응급구조", "언어치료", "청각재활", "의료"]),
                ("예술체육", ["뷰티", "스포츠", "그래픽", "디자인", "영상", "미디어",
                              "조리", "제과", "제빵", "음악", "체육"]),
                ("이공", ["AI", "컴퓨터", "소프트웨어", "공학", "철도", "건축", "전기",
                          "시스템", "빅데이터", "안전", "동물", "펫", "과학"]),
            ]
            # 자유전공학부는 규칙에서 제외한다 — 아직 전공을 정하지 않은 학생이라 계열을 단정할
            # 수 없고, 학과명에 '공학'이 부분 문자열로 들어 있어('자유전공학부') 이공으로 잘못
            # 걸리기까지 한다. NULL로 두면 마이페이지에서 학생이 직접 고른다.
            _EXCLUDE = "name NOT LIKE '%자유전공%'"
            for _field, _kws in _DEPT_FIELD_RULES:
                _cond = " OR ".join(f"name LIKE '%{k}%'" for k in _kws)
                await conn.execute(text(
                    f"UPDATE department SET major_field = '{_field}' "
                    f"WHERE major_field IS NULL AND {_EXCLUDE} AND ({_cond})"))
            # 어느 규칙에도 안 걸린 학과는 인문사회로 둔다(자유전공은 계속 NULL)
            await conn.execute(text(
                f"UPDATE department SET major_field = '인문사회' "
                f"WHERE major_field IS NULL AND {_EXCLUDE}"))

            # 수강 이력 컬럼 — '전체 기이수성적' 엑셀 업로드로 채운다(전부 nullable).
            # 기존 6행짜리 더미 데이터는 year/semester가 NULL로 남고, 중복 판정은
            # (student_id, course_code, year, semester)로 하므로 새 업로드와 충돌하지 않는다.
            for _col, _ddl in [("year", "INTEGER"), ("semester", "VARCHAR(20)"),
                               ("grade", "VARCHAR(10)"), ("grade_point", "DOUBLE PRECISION"),
                               ("retake_of", "VARCHAR(50)")]:
                await conn.execute(text(
                    f"ALTER TABLE student_course ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))

            # ── 외래키 인덱스 ────────────────────────────────────────
            # PostgreSQL은 FK를 걸어도 인덱스를 자동 생성하지 않는다. 조인·부모 행 삭제 때마다
            # 자식 테이블 풀스캔이 일어나므로 직접 만든다(멱등).
            # student_course.student_id는 졸업 현황·평점 계산이 매번 타는 경로라 특히 중요하고,
            # chat_message.student_id는 이미 만 행 가까이 쌓여 있다.
            for _idx, _tbl, _cols in [
                ("ix_student_course_student_id",     "student_course",     "student_id"),
                ("ix_student_course_course_code",    "student_course",     "course_code"),
                ("ix_student_dept_id",               "student",            "dept_id"),
                ("ix_requirement_set_dept_id",       "requirement_set",    "dept_id"),
                ("ix_requirement_rule_set_id",       "requirement_rule",   "set_id"),
                ("ix_department_college_id",         "department",         "college_id"),
                ("ix_department_division_id",        "department",         "division_id"),
                ("ix_division_college_id",           "division",           "college_id"),
                ("ix_student_achievement_student",   "student_achievement", "student_id"),
                ("ix_room_building_id",              "room",               "building_id"),
                ("ix_building_contact_building_id",  "building_contact",   "building_id"),
                ("ix_building_contact_office_id",    "building_contact",   "office_id"),
                ("ix_chat_message_student_id",       "chat_message",       "student_id"),
            ]:
                await conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {_idx} ON {_tbl} ({_cols})"))

            # 같은 수강(학생·과목·년도·학기)이 두 번 들어가면 졸업 학점이 부풀어 오른다.
            # 응용 계층(student_course_service)에서도 막지만, 다른 경로로 들어올 때를 대비해
            # DB에서도 막는다.
            #   · year IS NOT NULL 부분 인덱스 — 옛 더미 행은 year가 NULL이라 제외해야 충돌이 없다
            #   · semester는 COALESCE로 감싼다 — PostgreSQL은 NULL끼리 서로 다르다고 보아
            #     그냥 넣으면 학기가 NULL인 중복을 못 막는다
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_student_course_enrollment "
                "ON student_course (student_id, course_code, year, COALESCE(semester, '')) "
                "WHERE year IS NOT NULL"))
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

    # DB에서 활성 topic 로드 (신규 topic 시딩을 먼저 — 첫 기동부터 라우팅에 반영되도록)
    try:
        await _seed_my_grades_topic()
    except Exception as e:
        print(f"[Server] my_grades topic 시딩 실패 (무시): {e}")
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
    app.include_router(me_router,     prefix="/api",        tags=["마이페이지"])
    app.include_router(admins_router, prefix="/api/admins", tags=["관리자"])

    @app.get("/health", tags=["상태확인"])
    async def health():
        """서버 상태 확인"""
        return {"status": "ok"}

    return app
