"""장학금 카탈로그 조회 — '장학금 둘러보기' 모달 데이터.

RAG가 아니라 scholarship_catalog 테이블 직접 조회다. 넓은 목록 질문·마감 관리·검색을
DB로 확정적으로 처리한다(식단·학사일정을 RAG 없이 전용 조회로 주는 것과 같은 방식).

핵심 규칙:
- 마감 지난 장학금도 숨기지 않고 그대로 반환한다. 대신 end_at(마감 시각) < 지금(KST)이면
  expired=True를 실어 보내, 프론트가 '기간마감' 빨간 표시를 하고 '기간마감 숨기기' 토글로 걸러낸다.
  end_at이 NULL이면 상시(교내 성적우수·복지 등 매학기 반복)로 보고 만료되지 않는다.
- period는 화면 표시용 자유 텍스트, end_at은 만료 판정 전용(날짜+시간, 화면 비표시).
- 검색(q)은 이름·카테고리·조건을 대상으로 하는 DB ILIKE — GPU/LLM을 쓰지 않는다.
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, or_, func, update, delete, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import ScholarshipCatalog, ScholarshipFile, DocumentFile, Department, AppConfig

# 마감 판정은 한국시간(KST, DST 없음) 벽시계 기준. end_at도 KST 벽시계로 저장된 naive 값.
_KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    """현재 KST 시각(naive) — end_at(naive KST)과 직접 비교용."""
    return datetime.now(_KST).replace(tzinfo=None)


def _deadline_order():
    """카테고리 안 정렬 = 마감일 임박순.
    ① 마감 예정(가까운 순) → ② 상시(마감 없음) → ③ 기간마감, 같으면 이름순."""
    now = _now_kst()
    priority = case(
        (ScholarshipCatalog.end_at.is_(None), 1),   # 상시
        (ScholarshipCatalog.end_at < now, 2),        # 기간마감
        else_=0,                                      # 마감 예정
    )
    return [priority, ScholarshipCatalog.end_at.asc().nulls_last(), ScholarshipCatalog.name]


def _card_order():
    """카테고리 안 카드 정렬 — 관리자가 지정한 display_order 우선, 없으면(NULL) 마감임박순."""
    return [ScholarshipCatalog.display_order.asc().nulls_last(), *_deadline_order()]


# 카테고리 표시 순서는 app_config(key=_CAT_ORDER_KEY)에 이름 배열로 저장한다.
# (카테고리는 전용 테이블 없이 장학금의 자유 텍스트 컬럼이라 별도 순서 저장소가 필요)
_CAT_ORDER_KEY = "scholarship_category_order"


async def get_category_order(db: AsyncSession) -> list[str]:
    """저장된 카테고리 표시 순서(이름 배열). 없으면 빈 리스트."""
    row = await db.get(AppConfig, _CAT_ORDER_KEY)
    val = (row.value if row else None) or []
    return [c for c in val if isinstance(c, str)]


async def set_category_order(db: AsyncSession, categories: list[str]) -> None:
    """카테고리 표시 순서를 통째로 저장(관리자 화면의 위/아래 이동 결과)."""
    clean = [c for c in categories if isinstance(c, str) and c.strip()]
    row = await db.get(AppConfig, _CAT_ORDER_KEY)
    if row is None:
        db.add(AppConfig(key=_CAT_ORDER_KEY, value=clean))
    else:
        row.value = clean
    await db.commit()


async def set_scholarship_order(db: AsyncSession, ids: list[int]) -> int:
    """한 카테고리 안 장학금 표시 순서 저장 — 넘어온 id 순서대로 display_order 0,1,2…"""
    n = 0
    for idx, sid in enumerate(ids):
        row = await db.get(ScholarshipCatalog, sid)
        if row is not None:
            row.display_order = idx
            n += 1
    await db.commit()
    return n


def _sort_groups(groups: list[dict], order: list[str]) -> list[dict]:
    """카테고리 그룹을 저장된 순서대로. 순서에 없는 카테고리는 뒤에 이름순으로 붙인다."""
    pos = {c: i for i, c in enumerate(order)}
    return sorted(groups, key=lambda g: (pos.get(g["category"], len(pos)), g["category"]))


async def _load_files_map(db: AsyncSession, ids: list[int]) -> dict[int, list[dict]]:
    """장학금 id 목록에 연결된 파일들을 한 번에 조회 → {scholarship_id: [{topic,name,is_primary}, ...]}.

    대표(is_primary) 파일이 앞으로, 그다음 display_order·파일명 순. 모달이 첫 항목을
    대표로 보여주고 나머지는 펼침 목록으로 쓴다.
    """
    if not ids:
        return {}
    stmt = (
        select(
            ScholarshipFile.scholarship_id,
            DocumentFile.topic,
            DocumentFile.filename,
            ScholarshipFile.is_primary,
        )
        .join(DocumentFile, DocumentFile.id == ScholarshipFile.document_file_id)
        .where(ScholarshipFile.scholarship_id.in_(ids))
        .order_by(
            ScholarshipFile.is_primary.desc(),
            ScholarshipFile.display_order,
            DocumentFile.filename,
        )
    )
    rows = (await db.execute(stmt)).all()
    out: dict[int, list[dict]] = {}
    for sid, topic, fname, is_primary in rows:
        out.setdefault(sid, []).append(
            {"topic": topic, "name": fname, "is_primary": bool(is_primary)}
        )
    return out


def _to_item(row: ScholarshipCatalog, files: list[dict]) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "amount": row.amount,
        "eligibility": row.eligibility,
        "period": row.period,           # 화면 표시용 기간 텍스트
        "expired": bool(row.end_at and row.end_at < _now_kst()),  # end_at(시각) 지남 → '기간마감'
        "files": files,                 # 연결 파일 세트 (대표 우선)
        "link": row.link,
    }


async def get_catalog(
    db: AsyncSession,
    kind: str = "장학금",
    scope: str = "교내",
    q: str | None = None,
) -> dict:
    """kind(장학금/근로) + scope(교내/교외)로 걸러 카테고리별로 묶어 반환.

    반환: {kind, scope, count, groups: [{category, items:[...]}, ...]}
    - 마감 지난 것도 그대로 포함(항목에 expired 플래그). 숨김은 프론트 토글이 담당.
    - q가 있으면 이름·카테고리·조건에 대해 부분일치(대소문자 무시).
    """
    # scope가 '교내'/'교외'면 해당 scope만, 그 외('전체' 등)면 kind 안에서 scope 무관 전부.
    # (채팅 필터 카드 → 선택 카테고리가 교내·교외에 걸쳐 있어 cross-scope 조회가 필요)
    conds = [ScholarshipCatalog.kind == kind]
    if scope in ("교내", "교외"):
        conds.append(ScholarshipCatalog.scope == scope)
    stmt = select(ScholarshipCatalog).where(*conds)

    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ScholarshipCatalog.name.ilike(like),
                ScholarshipCatalog.category.ilike(like),
                ScholarshipCatalog.eligibility.ilike(like),
            )
        )

    # 카테고리로 묶고(그룹), 그 안은 관리자 지정 순서(display_order) → 마감일 임박순.
    stmt = stmt.order_by(
        ScholarshipCatalog.category.nulls_last(),
        *_card_order(),
    )

    rows = (await db.execute(stmt)).scalars().all()

    files_map = await _load_files_map(db, [r.id for r in rows])

    groups: list[dict] = []
    index: dict[str, dict] = {}
    for row in rows:
        cat = row.category or "기타"
        g = index.get(cat)
        if g is None:
            g = {"category": cat, "items": []}
            index[cat] = g
            groups.append(g)
        g["items"].append(_to_item(row, files_map.get(row.id, [])))

    groups = _sort_groups(groups, await get_category_order(db))   # 관리자 지정 카테고리 순서
    return {"kind": kind, "scope": scope, "count": len(rows), "groups": groups}


async def get_scope_counts(db: AsyncSession, kind: str = "장학금") -> dict:
    """탭 배지용 — 해당 kind의 scope별 건수(마감 포함). {'교내': n, '교외': m}"""
    stmt = (
        select(ScholarshipCatalog.scope, func.count())
        .where(ScholarshipCatalog.kind == kind)
        .group_by(ScholarshipCatalog.scope)
    )
    return {scope: n for scope, n in (await db.execute(stmt)).all()}


async def get_kind_counts(db: AsyncSession) -> dict:
    """상단 토글 배지용 — kind별 전체 건수. {'장학금': n, '근로': m}"""
    stmt = select(ScholarshipCatalog.kind, func.count()).group_by(ScholarshipCatalog.kind)
    return {kind: n for kind, n in (await db.execute(stmt)).all()}


async def build_scholarship_card(db: AsyncSession) -> dict:
    """채팅 장학금 필터 카드 데이터 — 장학금 카테고리(유형) 칩 목록.

    근로 제외, 카테고리 없는(None) 것 제외, 교내/교외 합쳐(cross-scope) 카테고리별 건수.
    학생이 카드에서 칩을 다중 선택하면 프론트가 둘러보기 모달을 그 카테고리들로 필터해서 연다.
    반환: {categories: [{category, count}, ...]} (건수 많은 순, 같으면 이름순)
    """
    stmt = (
        select(ScholarshipCatalog.category, func.count())
        .where(
            ScholarshipCatalog.kind == "장학금",
            ScholarshipCatalog.category.isnot(None),
        )
        .group_by(ScholarshipCatalog.category)
        .order_by(func.count().desc(), ScholarshipCatalog.category)
    )
    rows = (await db.execute(stmt)).all()
    return {"categories": [{"category": c, "count": n} for c, n in rows]}


# ─────────────────────────── 맞춤 설문 매칭 ───────────────────────────
# 소득 계층 순서 — 낮을수록 어려운 계층. 장학금 req_income='차상위'면 학생은 기초/차상위여야 통과.
# 소득 요건 = 국가장학금 학자금 지원구간 체계. req_income 값:
#   None(무관) / '복지'(복지자격 전용) / '1'~'10'(N구간 이하, 복지자격 포함)
# 복지자격(기초·차상위)은 최저구간 취급 → 'N구간 이하' 조건을 항상 통과.
# 레거시 값('중위100'·'중위200' 등 구간/복지가 아닌 값)은 판정 불가 → 무관 처리(관리자 재설정 대기).
_WELFARE = {"복지", "기초", "차상위"}


def _income_ok(req_income: str | None, student_income: str | None) -> bool:
    """장학금 소득 요건(req_income) 대비 학생 지원구간(student_income) 충족 여부.

    엄격 모드: 유효한 소득 요건(복지자격/구간)이 있는데 학생이 지원구간을 안 골랐으면(모름) 제외한다.
    (레거시 중위% 등 구간/복지가 아닌 값은 요건으로 인정하지 않고 무관 통과 — 관리자 재설정 대기.)
    """
    valid_req = (req_income in _WELFARE) or (bool(req_income) and req_income.isdigit())
    if not valid_req:
        return True                              # 요건 없음 / 레거시 → 무관 통과
    if not student_income:
        return False                             # 소득 요건 있는데 지원구간 미선택(모름) → 제외
    if req_income in _WELFARE:                    # '복지'·(레거시)'기초'·'차상위' = 복지자격 전용
        return student_income in _WELFARE
    # 'N구간 이하' 요건
    if student_income in _WELFARE:
        return True                              # 복지자격은 최저구간 → 통과
    if student_income.isdigit():
        return int(student_income) <= int(req_income)
    return False


def _norm_region(s: str | None) -> str:
    """지역 비교용 정규화 — 시/도/특별자치 등 접미사 제거해 '화성시'↔'화성' 매칭 유연화."""
    if not s:
        return ""
    s = s.strip()
    for suf in ("특별자치시", "특별자치도", "특별시", "광역시", "특별자치", "시", "군", "구", "도"):
        if len(s) > len(suf) and s.endswith(suf):
            return s[: -len(suf)]
    return s


# 시/도 (설문 드롭다운 값). _norm_region 후 형태.
_SIDO = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
         "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"}
# 시/군/구 → 소속 시/도. 장학금 대상지역이 '안산'(시/군)인데 학생은 시/도('경기')만 고르므로,
# 시/군을 그 도로 올려 매칭한다. (_norm_region으로 접미사 뗀 형태를 key로)
_SIDO_CITIES = {
    "서울": ["종로", "용산", "성동", "광진", "동대문", "중랑", "성북", "강북", "도봉", "노원",
             "은평", "서대문", "마포", "양천", "강서", "구로", "금천", "영등포", "동작", "관악",
             "서초", "강남", "송파", "강동"],
    "경기": ["수원", "성남", "의정부", "안양", "부천", "광명", "평택", "동두천", "안산", "고양",
             "과천", "구리", "남양주", "오산", "시흥", "군포", "의왕", "하남", "용인", "파주",
             "이천", "안성", "김포", "화성", "양주", "포천", "여주", "연천", "가평", "양평"],
    "강원": ["춘천", "원주", "강릉", "동해", "태백", "속초", "삼척", "홍천", "횡성", "영월",
             "평창", "정선", "철원", "화천", "양구", "인제", "고성", "양양"],
    "충북": ["청주", "충주", "제천", "보은", "옥천", "영동", "증평", "진천", "괴산", "음성", "단양"],
    "충남": ["천안", "공주", "보령", "아산", "서산", "논산", "계룡", "당진", "금산", "부여",
             "서천", "청양", "홍성", "예산", "태안"],
    "전북": ["전주", "군산", "익산", "정읍", "남원", "김제", "완주", "진안", "무주", "장수",
             "임실", "순창", "고창", "부안"],
    "전남": ["목포", "여수", "순천", "나주", "광양", "담양", "곡성", "구례", "고흥", "보성",
             "화순", "장흥", "강진", "해남", "영암", "무안", "함평", "영광", "장성", "완도", "진도", "신안"],
    "경북": ["포항", "경주", "김천", "안동", "구미", "영주", "영천", "상주", "문경", "경산",
             "의성", "청송", "영양", "영덕", "청도", "고령", "성주", "칠곡", "예천", "봉화", "울진", "울릉"],
    "경남": ["창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령", "함안",
             "창녕", "남해", "하동", "산청", "함양", "거창", "합천"],
    "제주": ["제주", "서귀포"],
}
_CITY_SIDO = {city: sido for sido, cities in _SIDO_CITIES.items() for city in cities}


def _region_to_sido(r: str) -> str | None:
    """정규화된 지역명을 시/도로 해석. 시/도면 자기 자신, 시/군이면 소속 시/도, 모르면 None."""
    if r in _SIDO:
        return r
    return _CITY_SIDO.get(r)


def _region_ok(req_region, basis, self_region, parent_region) -> bool:
    if not req_region:
        return True   # 무관
    r = _norm_region(req_region)
    r_sido = _region_to_sido(r)     # 대상지역이 시/군이면 소속 시/도 (안산→경기)
    if basis == "본인":
        cands = [self_region]
    elif basis == "부모":
        cands = [parent_region]
    else:
        cands = [self_region, parent_region]
    for c in cands:
        cn = _norm_region(c)
        if not cn or not r:
            continue
        if cn in r or r in cn:          # 직접 부분매칭 (같은 시/군·시/도 · '전북 / 서울' 복합표기 등)
            return True
        c_sido = _region_to_sido(cn)    # 학생 지역의 시/도 (안산→경기)
        # 광역(시/도) 단위 매칭은 '한쪽이 시/도일 때만'. 둘 다 시/군이면 위 정확매칭만 인정
        # (예: 학생 안산 ↔ 장학금 화성은 매칭 안 됨).
        if r in _SIDO and c_sido == r:      # 시/도 장학금 ↔ 학생 시/군 (경기 장학금 ↔ 안산 학생)
            return True
        if cn in _SIDO and r_sido == cn:    # 시/군 장학금 ↔ 학생 '○○ 전체'(시/도) (안산 장학금 ↔ 경기 전체 학생)
            return True
    return False


def _grade_ok(g: str, grade_year: int | None, semester: int | None = None,
              transfer: bool = False) -> bool:
    """학생 학년(grade_year)·학기(semester)·편입 여부가 요건 그룹 g에 해당하는지.
    신입=1학년 1학기, 재학=1학년 2학기부터. 1학년인데 학기 미상이면 관대하게 둘 다 통과.
    편입생은 학년이 아니라 신분이라 설문의 transfer 답으로 판정한다(편입 전용 장학금 대상)."""
    if g == "편입":
        return bool(transfer)                   # 편입생 전용 — 설문에서 편입생이라고 답해야 통과
    if g == "신입":
        # 1학년 1학기. 학기 미상(None)이면 통과, 2학기면 제외. 편입생은 신입 전형이 아니라 제외.
        return grade_year == 1 and semester != 2 and not transfer
    if g == "재학":
        # 2학년 이상, 또는 1학년 2학기(학기 미상도 관대하게 통과). 1학년 1학기(신입)는 제외.
        # 편입생은 재학생 신분이라 통과.
        if transfer:
            return True
        return grade_year is not None and (grade_year >= 2 or semester != 1)
    if g == "2학년이상":
        return grade_year is not None and grade_year >= 2   # 2·3·4학년
    if g == "3학년이상":
        return grade_year is not None and grade_year >= 3   # 3·4학년
    if g == "대학원":
        return False                            # 학부 더미라 대학원 전용은 제외
    return True


async def match_scholarships(
    db: AsyncSession,
    answers: dict,
    gpa: float | None = None,
    grade_year: int | None = None,
    major_field: str | None = None,
    dept_name: str | None = None,
    semester: int | None = None,
) -> dict:
    """설문 답 + 학생 더미(성적/학년/전공)로 장학금을 필터. 요건이 '무관(NULL/False)'이면 통과(폭넓게).
    반환: {count, items:[...]} — items는 모달 표시/딥링크용 _to_item 형태."""
    rows = (await db.execute(
        select(ScholarshipCatalog).where(ScholarshipCatalog.kind == "장학금").order_by(*_deadline_order())
    )).scalars().all()

    self_region = (answers.get("self_region") or "").strip()
    parent_region = (answers.get("parent_region") or "").strip()
    income = answers.get("income")
    interests = set(answers.get("interests") or [])
    want_excellent = "성적 우수" in interests   # '성적 우수'는 정렬이 아니라 태그 필터로 동작
    age = answers.get("age")
    transfer = bool(answers.get("transfer"))    # 편입생 여부 — 학년 요건 '편입' 판정용

    matched: list[ScholarshipCatalog] = []
    for r in rows:
        if not _region_ok(r.req_region, r.req_region_basis, self_region, parent_region):
            continue
        if r.req_min_gpa is not None and (gpa is None or gpa < r.req_min_gpa):
            continue
        # 학년 요건(다중) — 하나라도 충족하면 통과. 비면 무관.
        grades = [g for g in (r.req_grade or "").split(",") if g]
        if grades and not any(_grade_ok(g, grade_year, semester, transfer) for g in grades):
            continue
        if not _income_ok(r.req_income, income):
            continue   # 학생 지원구간이 요건 초과 → 대상 아님
        # 나이 범위 — 상한(이하)·하한(이상) 각각 선택. 학생이 나이를 안 넣으면(None) 무관 통과.
        if r.req_age_max is not None and age is not None and age > r.req_age_max:
            continue
        if r.req_age_min is not None and age is not None and age < r.req_age_min:
            continue
        # 전공계열(다중) — 학생 전공이 목록에 있으면 통과. 비면 무관.
        majors = [m for m in (r.req_major_field or "").split(",") if m]
        if majors and major_field and major_field not in majors:
            continue
        # 대상 학과(다중) — 학생 학과가 목록에 있으면 통과. 비면 무관.
        depts = [d for d in (r.req_departments or "").split(",") if d]
        if depts and dept_name and dept_name not in depts:
            continue
        # 대상 조건 플래그 — 여러 개 켜져 있으면 '하나라도 해당하면 통과'(OR).
        # 사회배려형(장애·보훈·다자녀 등)은 모두 충족(AND)이 아니라 택1이라서다.
        # 켜진 플래그가 하나도 없으면 무관(전원 통과). 단일 플래그(외국인 전용 등)는 그대로 필수처럼 동작.
        _req_flags = [
            (r.req_multichild, "multichild"), (r.req_foreigner, "foreigner"),
            (r.req_disabled, "disabled"), (r.req_independent, "independent"),
            (r.req_veteran, "veteran"),
            (r.req_multicultural, "multicultural"), (r.req_defector, "defector"),
        ]
        # 우대(preferential)면 대상 조건으로 거르지 않는다 — 일반 학생도 포함, 플래그는 안내·우대용.
        # 필수(기본)면 켜진 플래그 중 하나라도 해당해야 통과(OR).
        _required = [k for on, k in _req_flags if on]
        if _required and not r.req_flags_preferential and not any(answers.get(k) for k in _required):
            continue
        # '성적 우수'는 태그 필터(양방향): 체크하면 성적우수 태그만, 체크 안 하면 성적우수 태그는 제외.
        if bool(r.req_excellent) != want_excellent:
            continue
        matched.append(r)

    # 나머지 관심 유형(카테고리)은 '제외' 대신 '우선 정렬'(선택한 유형을 앞으로) — 놓침 방지 + 선호 반영.
    if interests:
        matched.sort(key=lambda r: 0 if (r.category or "기타") in interests else 1)

    files_map = await _load_files_map(db, [r.id for r in matched])
    return {"count": len(matched), "items": [_to_item(r, files_map.get(r.id, [])) for r in matched]}


# ─────────────────────────── 관리자: 파일 연결 관리 ───────────────────────────
async def list_catalog_min(db: AsyncSession) -> list[dict]:
    """파일 업로드 시 '소속 장학금' 드롭다운용 최소 목록."""
    stmt = select(
        ScholarshipCatalog.id,
        ScholarshipCatalog.name,
        ScholarshipCatalog.scope,
        ScholarshipCatalog.category,
    ).order_by(
        ScholarshipCatalog.scope,
        ScholarshipCatalog.category.nulls_last(),
        ScholarshipCatalog.name,
    )
    rows = (await db.execute(stmt)).all()
    return [{"id": r[0], "name": r[1], "scope": r[2], "category": r[3]} for r in rows]


async def link_file(db: AsyncSession, scholarship_id: int, document_file_id: int, is_primary: bool = False) -> None:
    """파일을 장학금에 연결. 파일 1개를 여러 장학금에 공유 가능 —
    이미 이 장학금에 연결돼 있으면 대표 여부만 갱신하고, 다른 장학금 연결은 건드리지 않는다.
    대표 지정 시 '같은 장학금'의 다른 파일 대표만 해제(대표는 장학금별 1개)."""
    existing = await db.scalar(
        select(ScholarshipFile).where(
            ScholarshipFile.scholarship_id == scholarship_id,
            ScholarshipFile.document_file_id == document_file_id,
        )
    )
    if existing:
        existing.is_primary = is_primary
    else:
        db.add(ScholarshipFile(
            scholarship_id=scholarship_id,
            document_file_id=document_file_id,
            is_primary=is_primary,
        ))
    if is_primary:
        # 같은 장학금의 다른 파일 대표 해제 (대표는 장학금별 1개)
        await db.execute(
            update(ScholarshipFile)
            .where(
                ScholarshipFile.scholarship_id == scholarship_id,
                ScholarshipFile.document_file_id != document_file_id,
            )
            .values(is_primary=False)
        )
    await db.commit()


async def unlink_file(db: AsyncSession, scholarship_id: int, document_file_id: int) -> None:
    """특정 장학금↔파일 연결만 해제 (파일 자체·다른 장학금의 연결은 유지)."""
    await db.execute(
        delete(ScholarshipFile).where(
            ScholarshipFile.scholarship_id == scholarship_id,
            ScholarshipFile.document_file_id == document_file_id,
        )
    )
    await db.commit()


async def get_file_links(db: AsyncSession) -> dict[int, list[dict]]:
    """{document_file_id: [{scholarship_id, scholarship_name, is_primary}, ...]} — 파일 목록 주석용.
    파일 1개가 여러 장학금에 연결될 수 있어 목록으로 반환한다."""
    stmt = (
        select(
            ScholarshipFile.document_file_id,
            ScholarshipFile.scholarship_id,
            ScholarshipCatalog.name,
            ScholarshipFile.is_primary,
        )
        .join(ScholarshipCatalog, ScholarshipCatalog.id == ScholarshipFile.scholarship_id)
        .order_by(ScholarshipFile.is_primary.desc(), ScholarshipCatalog.name)
    )
    rows = (await db.execute(stmt)).all()
    out: dict[int, list[dict]] = {}
    for doc_id, sid, name, is_primary in rows:
        out.setdefault(doc_id, []).append(
            {"scholarship_id": sid, "scholarship_name": name, "is_primary": bool(is_primary)}
        )
    return out


# ─────────────────────────── 관리자: 장학금 CRUD (장학금 관리 화면) ───────────────────────────
_REQ_FIELDS = (
    "req_region", "req_region_basis", "req_min_gpa", "req_grade", "req_income",
    "req_age_max", "req_major_field", "req_departments", "req_multichild", "req_foreigner",
    "req_disabled", "req_independent", "req_veteran", "req_excellent", "req_flags_preferential",
    "req_multicultural", "req_defector", "req_age_min",
)
_EDITABLE = ("name", "kind", "scope", "category", "amount", "eligibility", "period", "end_at", "link") + _REQ_FIELDS


def _admin_item(row: ScholarshipCatalog, files: list[dict]) -> dict:
    """관리자 편집용 직렬화 — end_at·요건 등 전체 필드 포함(모달용 _to_item과 달리 숨김 없음)."""
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "scope": row.scope,
        "category": row.category,
        "amount": row.amount,
        "eligibility": row.eligibility,
        "period": row.period,
        "end_at": row.end_at.isoformat() if row.end_at else None,
        "link": row.link,
        "expired": bool(row.end_at and row.end_at < _now_kst()),
        "files": files,   # [{topic, name, is_primary}]
        **{f: getattr(row, f) for f in _REQ_FIELDS},   # 맞춤 설문 매칭 요건
    }


async def list_department_names(db: AsyncSession) -> list[str]:
    """장학금 관리 '대상 학과' 다중선택용 — 학과명 목록(가나다순)."""
    rows = (await db.execute(select(Department.name).order_by(Department.name))).scalars().all()
    return [n for n in rows if n]


async def list_catalog_admin(db: AsyncSession) -> list[dict]:
    """장학금 관리 화면용 — 전체 + 연결 파일. 카테고리 안은 관리자 지정 순서→마감임박순."""
    stmt = select(ScholarshipCatalog).order_by(
        ScholarshipCatalog.category.nulls_last(),
        *_card_order(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    files_map = await _load_files_map(db, [r.id for r in rows])
    return [_admin_item(r, files_map.get(r.id, [])) for r in rows]


async def create_catalog(db: AsyncSession, data: dict) -> int:
    """장학금 1건 생성. data는 _EDITABLE 필드 dict. id 반환."""
    row = ScholarshipCatalog(**{k: data.get(k) for k in _EDITABLE})
    db.add(row)
    await db.commit()
    return row.id


async def update_catalog(db: AsyncSession, sid: int, data: dict) -> bool:
    """장학금 1건 수정. 없으면 False."""
    row = await db.get(ScholarshipCatalog, sid)
    if row is None:
        return False
    for k in _EDITABLE:
        if k in data:
            setattr(row, k, data[k])
    await db.commit()
    return True


async def delete_catalog(db: AsyncSession, sid: int) -> bool:
    """장학금 1건 삭제(연결 파일은 CASCADE로 해제, 파일 자체는 유지). 없으면 False."""
    row = await db.get(ScholarshipCatalog, sid)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
