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

from app.models.DB_Table import ScholarshipCatalog, ScholarshipFile, DocumentFile

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
    stmt = select(ScholarshipCatalog).where(
        ScholarshipCatalog.kind == kind,
        ScholarshipCatalog.scope == scope,
    )

    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ScholarshipCatalog.name.ilike(like),
                ScholarshipCatalog.category.ilike(like),
                ScholarshipCatalog.eligibility.ilike(like),
            )
        )

    # 카테고리로 묶고(그룹), 그 안은 마감일 임박순. NULL 카테고리는 맨 뒤로.
    stmt = stmt.order_by(
        ScholarshipCatalog.category.nulls_last(),
        *_deadline_order(),
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
    """파일을 장학금에 연결(문서당 장학금 1개 → 있으면 재지정). 대표 지정 시 같은 장학금의 기존 대표는 해제."""
    existing = await db.scalar(
        select(ScholarshipFile).where(ScholarshipFile.document_file_id == document_file_id)
    )
    if existing:
        existing.scholarship_id = scholarship_id
        existing.is_primary = is_primary
    else:
        db.add(ScholarshipFile(
            scholarship_id=scholarship_id,
            document_file_id=document_file_id,
            is_primary=is_primary,
        ))
    if is_primary:
        # 같은 장학금의 다른 파일 대표 해제 (대표는 1개만)
        await db.execute(
            update(ScholarshipFile)
            .where(
                ScholarshipFile.scholarship_id == scholarship_id,
                ScholarshipFile.document_file_id != document_file_id,
            )
            .values(is_primary=False)
        )
    await db.commit()


async def unlink_file(db: AsyncSession, document_file_id: int) -> None:
    """파일-장학금 연결 해제 (파일 자체는 삭제하지 않음)."""
    await db.execute(delete(ScholarshipFile).where(ScholarshipFile.document_file_id == document_file_id))
    await db.commit()


async def get_file_links(db: AsyncSession) -> dict[int, dict]:
    """{document_file_id: {scholarship_id, scholarship_name, is_primary}} — 파일 목록 주석용."""
    stmt = (
        select(
            ScholarshipFile.document_file_id,
            ScholarshipFile.scholarship_id,
            ScholarshipCatalog.name,
            ScholarshipFile.is_primary,
        )
        .join(ScholarshipCatalog, ScholarshipCatalog.id == ScholarshipFile.scholarship_id)
    )
    rows = (await db.execute(stmt)).all()
    return {
        r[0]: {"scholarship_id": r[1], "scholarship_name": r[2], "is_primary": bool(r[3])}
        for r in rows
    }


# ─────────────────────────── 관리자: 장학금 CRUD (장학금 관리 화면) ───────────────────────────
_EDITABLE = ("name", "kind", "scope", "category", "amount", "eligibility", "period", "end_at", "link")


def _admin_item(row: ScholarshipCatalog, files: list[dict]) -> dict:
    """관리자 편집용 직렬화 — end_at 등 전체 필드 포함(모달용 _to_item과 달리 숨김 없음)."""
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
    }


async def list_catalog_admin(db: AsyncSession) -> list[dict]:
    """장학금 관리 화면용 — 전체 + 연결 파일. kind→scope→카테고리→마감일 임박순."""
    stmt = select(ScholarshipCatalog).order_by(
        ScholarshipCatalog.kind,
        ScholarshipCatalog.scope,
        ScholarshipCatalog.category.nulls_last(),
        *_deadline_order(),
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
