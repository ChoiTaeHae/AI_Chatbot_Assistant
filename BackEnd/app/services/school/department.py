"""
학과/학부/단과대학 안내 (DB 조회 — RAG 미사용)

학과소개 본문을 벡터DB에 넣어두면 학교가 교육과정을 개편해도 우리 복사본은 옛
내용으로 남는다. 실제로 college_department 토픽엔 문서가 2건뿐이라 "컴공 소개해줘"에
엉뚱한 대학 소개가 나왔다. 여기서는 DB가 확실히 아는 소속 정보(단과대/학부/형제 학과)만
답하고 상세 소개는 학과 홈페이지 링크로 넘긴다 — campus.py가 카카오맵 링크를 주는 것과
같은 방식이다.

answer_department_question()은 {answer, dept_card, found} 를 반환하고,
dept_card는 프론트 말풍선 안에 카드로 렌더된다(사이드바 자리를 쓰지 않는다).
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import College, Department, Division

# 매칭 캐시 — (종류, id, 표시명, 매칭어 목록). 첫 질문 때 1회 로드.
_CACHE: list[tuple[str, int, str, list[str]]] | None = None
# {dept_id: {"college": str|None, "division": str|None, "homepage_url": str|None}}
_DEPT_INFO: dict[int, dict] = {}


def _norm(s: str) -> str:
    """비교용 정규화 — 괄호 안 내용·공백·구분자 제거 + 소문자.

    괄호를 지우는 이유: DB는 '소프트웨어(SW)융합대학'인데 학생은 '소프트웨어융합대학'
    이라고 쓴다. graduation.py의 _norm은 괄호를 안 지우지만 거기엔 괄호 낀 학과명이
    없어 문제가 없었다.
    """
    s = re.sub(r"\([^)]*\)", "", s or "")
    return re.sub(r"[\s·․/,]", "", s).lower()


async def _ensure_cache(db: AsyncSession) -> None:
    """학과·학부·단과대 매칭 캐시 지연 로드 (첫 학과 질문 시 1회)."""
    global _CACHE
    if _CACHE is not None:
        return

    colleges = {c.id: c.name for c in (await db.execute(select(College))).scalars()}
    divisions = {d.id: (d.name, d.college_id) for d in (await db.execute(select(Division))).scalars()}
    depts = (await db.execute(select(Department))).scalars().all()

    cache: list[tuple[str, int, str, list[str]]] = []
    for d in depts:
        cache.append(("department", d.id, d.name, [d.name, *(d.aliases or [])]))
        _DEPT_INFO[d.id] = {
            "college": colleges.get(d.college_id),
            "division": divisions.get(d.division_id, (None, None))[0],
            "homepage_url": getattr(d, "homepage_url", None),
            "phone": getattr(d, "phone", None),
        }
    for did, (name, _cid) in divisions.items():
        cache.append(("division", did, name, [name]))
    for cid, name in colleges.items():
        cache.append(("college", cid, name, [name]))

    _CACHE = cache
    print(f"[Department] 매칭 캐시 로드 — 학과 {len(depts)} / 학부 {len(divisions)} / 단과대 {len(colleges)}")


def reset_cache() -> None:
    """어드민에서 학과 정보를 수정했을 때 캐시 무효화."""
    global _CACHE
    _CACHE = None
    _DEPT_INFO.clear()


def _detect(question: str) -> tuple[str, int, str] | None:
    """질문에서 학과/학부/단과대를 탐지해 (종류, id, 표시명) 반환.

    가장 긴 매칭이 이긴다 — '컴퓨터·소프트웨어전공'을 물었을 때 짧은 별칭 '소프트웨어학과'나
    '소프트웨어학부'에 먼저 걸리는 부분매칭 오탐을 막는다.
    """
    if not _CACHE:
        return None
    q = _norm(question)
    best: tuple[int, str, int, str] | None = None   # (매칭길이, 종류, id, 표시명)
    for kind, oid, label, terms in _CACHE:
        for term in terms:
            nt = _norm(term)
            if nt and nt in q and (best is None or len(nt) > best[0]):
                best = (len(nt), kind, oid, label)
    return (best[1], best[2], best[3]) if best else None


# 키워드 매칭에서 걷어낼 일반어 — 이게 키워드로 남으면 '학과'가 전 학과를 다 잡는 식이 된다.
_DEPT_STOPWORDS = (
    "관련", "학과", "전공", "학부", "단과대학", "단과대", "대학교", "대학", "계열",
    "뭐가", "뭐", "무슨", "어떤", "어느", "있어요", "있나요", "있어", "있나", "있는", "있니",
    "목록", "종류", "리스트", "알려줘", "알려", "소개", "추천", "정보", "대해서", "대해", "관하여",
)


def _keyword_departments(question: str) -> tuple[str, list[str]]:
    """정확 매칭이 실패했을 때, 일반어를 걷어낸 '키워드'가 학과명·별칭 일부에 들어가면 관련 학과를
    나열한다. 반환 (키워드, [학과명…]). 키워드가 없거나 매칭이 없으면 ("", []).
    예: '철도 관련학과 뭐있어' → ('철도', ['글로벌철도학과','철도경영학과', …])
    """
    if not _CACHE:
        return "", []
    q = question
    for w in _DEPT_STOPWORDS:
        q = q.replace(w, " ")
    tokens = [t for t in re.findall(r"[가-힣A-Za-z]+", q) if len(t) >= 2]
    for kw in tokens:
        nkw = _norm(kw)
        if len(nkw) < 2:
            continue
        matches = sorted({
            label for kind, _oid, label, terms in _CACHE
            if kind == "department" and any(nkw in _norm(t) for t in terms)
        })
        if matches:
            return kw, matches
    return "", []


def _josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """받침 유무에 맞는 조사 선택 ('간호학과는' / '컴퓨터공학전공은').
    한글로 끝나지 않으면 병기('은(는)')로 안전하게 처리한다."""
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣":
        return with_batchim if (ord(ch) - 0xAC00) % 28 else without_batchim
    return f"{with_batchim}({without_batchim})"


_HOMEPAGE_GUIDE = "교육과정·입학·취업 등 자세한 소개는 학과 홈페이지에서 확인하실 수 있습니다."


async def _department_card(db: AsyncSession, dept_id: int, name: str) -> tuple[str, dict]:
    info = _DEPT_INFO.get(dept_id, {})
    college, division = info.get("college"), info.get("division")

    # 형제 학과는 '같은 학부'일 때만 보여준다. 학부 없는 단과대 직속 학과까지 형제로 묶으면
    # 보건복지대학처럼 직속이 12개인 곳에서 관계없는 학과 11개가 답변에 쏟아진다.
    if division:
        id_to_name = {oid: label for kind, oid, label, _t in (_CACHE or []) if kind == "department"}
        siblings = sorted(
            id_to_name[d] for d in _DEPT_INFO
            if _DEPT_INFO[d].get("division") == division and d != dept_id and d in id_to_name
        )
    else:
        siblings = []

    subtitle = " · ".join(x for x in (college, division) if x) or "우송대학교"

    if college:
        belong = f"{college} {division}" if division else college
        answer = f"**{name}**{_josa(name, '은', '는')} {belong} 소속입니다."
    else:
        # college_id가 비어있는 학과 (예: 자유전공학부) — 없는 소속을 지어내지 않는다
        answer = f"**{name}** 안내입니다. 소속 단과대학 정보는 등록되어 있지 않습니다."

    if siblings:
        last = siblings[-1]
        answer += f"\n\n같은 학부에 {', '.join(siblings)}{_josa(last, '이', '가')} 있습니다."
    if info.get("phone"):
        answer += f"\n\n학과 사무실: {info['phone']}"
    answer += f"\n\n{_HOMEPAGE_GUIDE}"

    return answer, {
        "kind": "department",
        "title": name,
        "subtitle": subtitle,
        "items_label": "같은 학부",
        "items": siblings,
        "phone": info.get("phone"),
        "homepage_url": info.get("homepage_url"),
    }


async def _division_card(db: AsyncSession, division_id: int, name: str) -> tuple[str, dict]:
    div = await db.get(Division, division_id)
    college = (await db.get(College, div.college_id)).name if div and div.college_id else None
    members = sorted(
        d.name for d in (await db.execute(
            select(Department).where(Department.division_id == division_id)
        )).scalars()
    )

    answer = (f"**{name}**{_josa(name, '은', '는')} {college} 소속 학부입니다."
              if college else f"**{name}** 안내입니다.")
    if members:
        answer += f"\n\n소속 전공: {', '.join(members)}"
    answer += "\n\n각 전공의 자세한 소개는 학과 홈페이지에서 확인하실 수 있습니다."

    return answer, {
        "kind": "division",
        "title": name,
        "subtitle": college or "학부",
        "items_label": "소속 전공",
        "items": members,
        "phone": None,
        "homepage_url": None,
    }


async def _college_card(db: AsyncSession, college_id: int, name: str) -> tuple[str, dict]:
    divisions = sorted(
        d.name for d in (await db.execute(
            select(Division).where(Division.college_id == college_id)
        )).scalars()
    )
    direct = sorted(
        d.name for d in (await db.execute(
            select(Department).where(
                Department.college_id == college_id, Department.division_id.is_(None)
            )
        )).scalars()
    )
    members = divisions + direct

    answer = f"**{name}** 소속 학부/학과입니다."
    if divisions:
        answer += f"\n\n학부: {', '.join(divisions)}"
    if direct:
        answer += f"\n\n학과: {', '.join(direct)}"
    answer += "\n\n궁금한 학과 이름을 말씀해 주시면 소속과 홈페이지를 안내해 드릴게요."

    return answer, {
        "kind": "college",
        "title": name,
        "subtitle": "단과대학",
        "items_label": "소속 학부·학과",
        "items": members,
        "phone": None,
        "homepage_url": None,
    }


def _keyword_card(keyword: str, names: list[str]) -> tuple[str, dict]:
    """키워드로 찾은 관련 학과 목록 카드. (프론트는 title/subtitle/items만 렌더 — kind 무관)"""
    answer = (
        f"'{keyword}' 관련 학과는 다음과 같습니다.\n\n"
        f"{', '.join(names)}\n\n"
        "궁금한 학과 이름을 말씀해 주시면 소속과 홈페이지를 안내해 드릴게요."
    )
    return answer, {
        "kind": "keyword",
        "title": f"'{keyword}' 관련 학과",
        "subtitle": f"{len(names)}개 학과",
        "items_label": "관련 학과",
        "items": names,
        "phone": None,
        "homepage_url": None,
    }


async def _not_found(db: AsyncSession) -> tuple[str, None]:
    colleges = sorted(c.name for c in (await db.execute(select(College))).scalars())
    answer = (
        "어느 학과를 말씀하시는지 찾지 못했습니다. 학과 이름을 정확히 알려주시면 안내해 드릴게요.\n\n"
        f"단과대학: {', '.join(colleges)}"
    )
    return answer, None


async def answer_department_question(question: str, db: AsyncSession) -> dict:
    """학과/학부/단과대 질문에 DB로 답한다. {answer, dept_card, found} 반환."""
    await _ensure_cache(db)

    hit = _detect(question)
    if not hit:
        # 정확 매칭 실패 → 키워드로 관련 학과 유연 매칭 ('철도 관련학과' → 철도* 학과들)
        kw, names = _keyword_departments(question)
        if names:
            print(f"[Department] 키워드 '{kw}' 관련 학과 {len(names)}개")
            answer, card = _keyword_card(kw, names)
            return {"answer": answer, "dept_card": card, "found": True}
        print("[Department] 학과/학부/단과대 미탐지")
        answer, card = await _not_found(db)
        return {"answer": answer, "dept_card": card, "found": False}

    kind, oid, name = hit
    print(f"[Department] 매칭 → {kind} '{name}'")

    if kind == "department":
        answer, card = await _department_card(db, oid, name)
    elif kind == "division":
        answer, card = await _division_card(db, oid, name)
    else:
        answer, card = await _college_card(db, oid, name)

    return {"answer": answer, "dept_card": card, "found": True}
