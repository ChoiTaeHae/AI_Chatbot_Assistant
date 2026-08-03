"""학과 관리 (관리자) — College/Division/Department CRUD.

챗봇 '학과 소개'(department.py)와 **같은 테이블**을 관리한다. 여기서 단과대·학부·학과를
추가·수정·삭제하면 department.reset_cache()로 챗봇 매칭 캐시를 무효화해 다음 질문부터
바로 반영된다.

학과명을 바꾸면 장학금 '대상 학과'(scholarship_catalog.req_departments — 이름 기반
콤마 목록)도 함께 고쳐 매칭이 깨지지 않게 한다. (학생·요건은 dept_id로 연결돼 이름 변경
영향을 받지 않는다.)
"""
import re

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import College, Division, Department, ScholarshipCatalog, Student
from app.services.school import department as dept_chat   # reset_cache()


# ─────────────────────────────── 조회 (트리) ───────────────────────────────

def _dept_dict(d: Department, counts: dict[int, int]) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "aliases": d.aliases or [],
        "college_id": d.college_id,
        "division_id": d.division_id,
        "homepage_url": d.homepage_url,
        "phone": d.phone,
        "student_count": counts.get(d.id, 0),
    }


async def get_dept_tree(db: AsyncSession) -> dict:
    """단과대학 → 학부 → 학과 계층 구조. 학부 없는 학과는 단과대 직속, 단과대도 없으면 '미분류'."""
    colleges = (await db.execute(select(College).order_by(College.name))).scalars().all()
    divisions = (await db.execute(select(Division).order_by(Division.name))).scalars().all()
    depts = (await db.execute(select(Department).order_by(Department.name))).scalars().all()
    counts = {
        did: n for did, n in (await db.execute(
            select(Student.dept_id, func.count()).where(Student.dept_id.isnot(None)).group_by(Student.dept_id)
        )).all()
    }

    divs_by_college: dict[int, list[Division]] = {}
    for dv in divisions:
        divs_by_college.setdefault(dv.college_id, []).append(dv)

    depts_by_division: dict[int, list[Department]] = {}
    direct_by_college: dict[int, list[Department]] = {}   # 학부 없는 단과대 직속
    unassigned: list[Department] = []                     # 단과대도 없는 학과 (예: 자유전공학부)
    for d in depts:
        if d.college_id is None:
            unassigned.append(d)
        elif d.division_id is not None:
            depts_by_division.setdefault(d.division_id, []).append(d)
        else:
            direct_by_college.setdefault(d.college_id, []).append(d)

    tree = []
    for c in colleges:
        tree.append({
            "id": c.id,
            "name": c.name,
            "divisions": [
                {
                    "id": dv.id,
                    "name": dv.name,
                    "departments": [_dept_dict(x, counts) for x in depts_by_division.get(dv.id, [])],
                }
                for dv in divs_by_college.get(c.id, [])
            ],
            "departments": [_dept_dict(x, counts) for x in direct_by_college.get(c.id, [])],
        })

    return {
        "colleges": tree,
        "unassigned": [_dept_dict(x, counts) for x in unassigned],
    }


# ─────────────────────────────── 단과대학 (College) ───────────────────────────────

async def create_college(db: AsyncSession, name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("단과대학 이름은 필수입니다.")
    if await db.scalar(select(College).where(College.name == name)):
        raise ValueError("이미 있는 단과대학입니다.")
    c = College(name=name)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    dept_chat.reset_cache()
    return c.id


async def update_college(db: AsyncSession, cid: int, name: str) -> bool:
    c = await db.get(College, cid)
    if not c:
        return False
    name = (name or "").strip()
    if not name:
        raise ValueError("단과대학 이름은 필수입니다.")
    dup = await db.scalar(select(College).where(College.name == name, College.id != cid))
    if dup:
        raise ValueError("이미 있는 단과대학입니다.")
    c.name = name
    await db.commit()
    dept_chat.reset_cache()
    return True


async def delete_college(db: AsyncSession, cid: int) -> bool:
    c = await db.get(College, cid)
    if not c:
        return False
    n_div = await db.scalar(select(func.count()).select_from(Division).where(Division.college_id == cid))
    n_dept = await db.scalar(select(func.count()).select_from(Department).where(Department.college_id == cid))
    if n_div or n_dept:
        raise ValueError("하위 학부·학과가 있어 삭제할 수 없습니다. 먼저 옮기거나 삭제하세요.")
    await db.delete(c)
    await db.commit()
    dept_chat.reset_cache()
    return True


# ─────────────────────────────── 학부 (Division) ───────────────────────────────

async def create_division(db: AsyncSession, name: str, college_id: int) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("학부 이름은 필수입니다.")
    if not college_id:
        raise ValueError("소속 단과대학을 선택하세요.")
    if not await db.get(College, college_id):
        raise ValueError("단과대학을 찾을 수 없습니다.")
    dup = await db.scalar(select(Division).where(Division.name == name, Division.college_id == college_id))
    if dup:
        raise ValueError("이미 있는 학부입니다.")
    dv = Division(name=name, college_id=college_id)
    db.add(dv)
    await db.commit()
    await db.refresh(dv)
    dept_chat.reset_cache()
    return dv.id


async def update_division(db: AsyncSession, did: int, name: str, college_id: int) -> bool:
    dv = await db.get(Division, did)
    if not dv:
        return False
    name = (name or "").strip()
    if not name:
        raise ValueError("학부 이름은 필수입니다.")
    if not college_id:
        raise ValueError("소속 단과대학을 선택하세요.")
    dup = await db.scalar(
        select(Division).where(Division.name == name, Division.college_id == college_id, Division.id != did)
    )
    if dup:
        raise ValueError("이미 있는 학부입니다.")
    moved = dv.college_id != college_id
    dv.name = name
    dv.college_id = college_id
    # 학부의 단과대가 바뀌면 소속 학과의 college_id도 함께 맞춘다 (트리 일관성)
    if moved:
        for d in (await db.execute(select(Department).where(Department.division_id == did))).scalars():
            d.college_id = college_id
    await db.commit()
    dept_chat.reset_cache()
    return True


async def delete_division(db: AsyncSession, did: int) -> bool:
    dv = await db.get(Division, did)
    if not dv:
        return False
    n_dept = await db.scalar(select(func.count()).select_from(Department).where(Department.division_id == did))
    if n_dept:
        raise ValueError("소속 학과가 있어 삭제할 수 없습니다. 먼저 옮기거나 삭제하세요.")
    await db.delete(dv)
    await db.commit()
    dept_chat.reset_cache()
    return True


# ─────────────────────────────── 학과 (Department) ───────────────────────────────

def _norm_aliases(raw) -> list[str] | None:
    """별칭 입력 정규화 — 콤마/줄바꿈 구분 문자열 또는 리스트를 받아 빈 값 제거."""
    if raw is None:
        return None
    items = [x.strip() for x in re.split(r"[,\n]", raw)] if isinstance(raw, str) else [str(x).strip() for x in raw]
    items = [x for x in items if x]
    return items or None


async def _sync_scholarship_departments(db: AsyncSession, old_name: str, new_name: str) -> int:
    """학과명 변경 시 장학금 '대상 학과' 콤마 목록의 옛 이름을 새 이름으로 교체. 변경된 장학금 수 반환."""
    rows = (await db.execute(
        select(ScholarshipCatalog).where(ScholarshipCatalog.req_departments.isnot(None))
    )).scalars().all()
    changed = 0
    for r in rows:
        parts = (r.req_departments or "").split(",")
        if old_name not in parts:
            continue
        seen: set[str] = set()
        out: list[str] = []
        for name in parts:
            v = new_name if name == old_name else name
            if v and v not in seen:   # 빈 값 제거 + new_name이 이미 있었으면 중복 제거
                seen.add(v)
                out.append(v)
        r.req_departments = ",".join(out) if out else None
        changed += 1
    return changed


async def create_department(db: AsyncSession, data: dict) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("학과 이름은 필수입니다.")
    if await db.scalar(select(Department).where(Department.name == name)):
        raise ValueError("이미 있는 학과입니다.")
    d = Department(
        name=name,
        aliases=_norm_aliases(data.get("aliases")),
        college_id=data.get("college_id") or None,
        division_id=data.get("division_id") or None,
        homepage_url=(data.get("homepage_url") or "").strip() or None,
        phone=(data.get("phone") or "").strip() or None,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    dept_chat.reset_cache()
    return d.id


async def update_department(db: AsyncSession, did: int, data: dict):
    """학과 수정. 없으면 False, 있으면 {'renamed_scholarships': n} 반환."""
    d = await db.get(Department, did)
    if not d:
        return False
    new_name = (data.get("name") or "").strip()
    if not new_name:
        raise ValueError("학과 이름은 필수입니다.")
    dup = await db.scalar(select(Department).where(Department.name == new_name, Department.id != did))
    if dup:
        raise ValueError("이미 있는 학과입니다.")

    old_name = d.name
    d.name = new_name
    d.aliases = _norm_aliases(data.get("aliases"))
    d.college_id = data.get("college_id") or None
    d.division_id = data.get("division_id") or None
    d.homepage_url = (data.get("homepage_url") or "").strip() or None
    d.phone = (data.get("phone") or "").strip() or None

    renamed = 0
    if old_name != new_name:
        renamed = await _sync_scholarship_departments(db, old_name, new_name)

    await db.commit()
    dept_chat.reset_cache()
    return {"renamed_scholarships": renamed}


async def delete_department(db: AsyncSession, did: int) -> bool:
    d = await db.get(Department, did)
    if not d:
        return False
    try:
        await db.delete(d)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ValueError("이 학과를 참조하는 학생·요건 데이터가 있어 삭제할 수 없습니다.")
    dept_chat.reset_cache()
    return True
