"""내 성적 조회 — 마이페이지에 올린 수강 이력(student_course)으로 학기별 과목·등급·평점을 답한다.

RAG도 LLM도 타지 않는다. 성적은 학생 본인의 사실 데이터라, 문장을 생성하는 과정에서 숫자
하나가 흔들리면 그대로 오답이 된다(졸업 학점 현황·학식 안내와 같은 원칙). 표는 코드로 만든다.

'몇 학년 몇 학기'는 DB에 없다 — 포털의 '전체 기이수성적' 엑셀에는 년도(2025)와 학기(1학기)만
있다. 그래서 '등록한 학년도의 순번'을 학년으로 쓴다. 첫 해가 1학년, 다음 등록한 해가 2학년이며
한 해 안의 1학기·2학기·계절학기는 모두 같은 학년이다. 휴학해 등록하지 않은 해는 행이 없어
자연히 건너뛰어진다.

정규학기 개수를 2로 나누는 방식은 쓰지 않는다. 한 학기만 이수한 해가 있으면 그 뒤의 학년
경계가 반 학기씩 밀려 같은 학년도의 1·2학기가 다른 학년으로 갈린다(실측 사례는 _build_terms 참조).

이 매핑이 이 서비스에서 유일하게 '추정'이 섞이는 지점이라, 답변에는 항상
'2학년 1학기 (2025년 1학기)'처럼 실제 년도·학기를 함께 적는다 — 어긋났을 때 학생이 바로
알아볼 수 있어야 한다.
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import Course, Student, StudentCourse

GRADE_SCALE = 4.5

# 학기 정렬 순서 — 같은 해 안에서 1학기 → 여름 → 2학기 → 겨울.
# 여름학기를 2학기 뒤에 두면 '직전 정규학기'가 어긋나 학년 라벨이 한 학기 밀린다.
_TERM_RANK = {"1학기": 1, "여름학기": 2, "하계학기": 2, "2학기": 3, "겨울학기": 4, "동계학기": 4}
_REGULAR_TERMS = ("1학기", "2학기")

# 과목표 정렬 — 이수구분을 학사 통용 순서로 고정한다(가나다순이면 교양이 전공보다 위로 온다).
_CATEGORY_RANK = {"전공필수": 1, "전공선택": 2, "교양필수": 3, "교양선택": 4, "트랙": 5, "일반": 6}

# 학기별 과목표를 몇 개까지 펼칠지. 이 이상이면 학기 요약표로 바꾼다 —
# '2학년 성적'은 두 학기라 과목표가 적당하지만, 전체 8학기를 과목표로 풀면 말풍선이 화면을 넘긴다.
_MAX_DETAIL_TERMS = 2


# ── 질문 파싱 ──────────────────────────────────────────────────────
# 순서가 곧 우선순위다. '2학년 1학기'는 학년+학기로 먼저 잡아야 하며,
# 뒤의 '학기만' 패턴이 먼저 걸리면 학년이 통째로 무시된다.
_RE_GRADE_TERM = re.compile(r"([1-9])\s*학년\s*(?:제\s*)?([12])\s*학기")
_RE_GRADE_SEASON = re.compile(r"([1-9])\s*학년\s*(여름|겨울|하계|동계|계절)\s*학기")
_RE_YEAR_TERM = re.compile(r"((?:19|20)\d{2})\s*년\s*도?\s*(?:제\s*)?([12])\s*학기")
_RE_YEAR_SEASON = re.compile(r"((?:19|20)\d{2})\s*년\s*도?\s*(여름|겨울|하계|동계|계절)\s*학기")
_RE_GRADE = re.compile(r"([1-9])\s*학년")
_RE_YEAR = re.compile(r"((?:19|20)\d{2})\s*년")
_RE_TERM_ONLY = re.compile(r"([12])\s*학기")
_RE_SEASON_ONLY = re.compile(r"(여름|겨울|하계|동계|계절)\s*학기")
_RE_LATEST = re.compile(r"이번\s*학기|최근|마지막|막학기")
_RE_PREV_TERM = re.compile(r"지난\s*학기|저번\s*학기|전\s*학기")
# 학년·년도 없이 학기만 말한 후속 질문('2학기는?')에 직전 질문의 학년을 빌려주기 위한 판정용.
_RE_ANY_TERM = re.compile(r"[12]\s*학기|여름\s*학기|겨울\s*학기|계절\s*학기")

# 성적 '제도·절차'를 묻는 신호 — 이게 있으면 개인 데이터로 답할 질문이 아니다.
# (라우터가 성적 규정 질문을 이 핸들러로 보내도 여기서 알아채고 RAG로 넘긴다)
_PROCEDURE_RE = re.compile(
    r"어떻게|방법|절차|기준|규정|산정|계산|신청|이의|정정|포기|학사경고|경고|제적|재수강|"
    r"추천|개설|들어야|어디서|어디에서|장학|등록금|증명서|성적표\s*발급"
)


# ── '개인 성적표 요청인가' 판정 ────────────────────────────────────
# 라우팅 판정을 여기 한 곳에 모은다. agent_graph의 키워드 fast-path와 핸들러의 재검증이
# 같은 규칙을 써야, 한쪽만 고쳐 두 판정이 어긋나는 일이 생기지 않는다.
#
# 어휘를 세기(强)와 약기(弱)로 나눈 근거 — 실제 질문 2,356종 전수 검증
#   '성적·평점·등급·성적표·수강이력'은 성적표를 달라는 말에 가깝다(세기).
#   '학점·과목·점수'는 졸업요건("졸업하려면 몇 학점")과 수강신청 규정("1학기 최대 학점")이
#   똑같이 쓴다(약기). 둘을 같이 묶었더니 "나 졸업하려면 몇 학점 필요해?"·"내 졸업학점
#   얼마나 남았어?" 등 졸업 핸들러가 답하던 9종을 통째로 가로챘다.
_REPORT_RE = re.compile(r"성적|평점|등급|성적표|수강\s*이력|이수\s*내역")
_WEAK_RE = re.compile(r"학점|과목|점수")
_PERIOD_RE = re.compile(
    r"[1-9]\s*학년|[12]\s*학기|(?:19|20)\d{2}\s*년|여름학기|겨울학기|계절학기|"
    r"이번\s*학기|지난\s*학기|저번\s*학기|막학기"
)
# '내년'·'안내'처럼 다른 낱말 속의 '내'가 걸리지 않도록 앞뒤를 좁힌다(graduation과 같은 패턴).
_FIRST_PERSON_RE = re.compile(r"(?:^|\s)(?:내|제|저|나)(?:\s|가|는|의|를|도)|본인|내가|제가|나의")
# 시점이 붙어 있어도 이 말이 있으면 개인 성적표 질문이 아니다.
#   졸업·편입·수료 → 졸업요건 / 최대 → 수강신청 상한 / 남았·부족·필요 → 졸업 잔여학점
_OTHER_DOMAIN_RE = re.compile(r"졸업|편입|수료|최대|남았|남은|부족|필요")
# 시점 말고는 아무 내용어가 없는 파편 — '2학기는?', '3학년은?', '1학년 2학기는?'.
# 이런 파편은 스스로 주제를 못 밝히는데, 임베딩은 '학기'라는 일반어만 보고 my_grades를
# 0.67~0.71로 확신해 버린다(전수 감사에서 4종 적발: 2위 graduation·school_rules와 0.006~0.03 차).
# 그래서 직전에도 성적을 물었을 때만 개인 조회로 잇는다.
_FRAGMENT_RE = re.compile(
    r"^\s*(?:그럼|그러면|그리고|그럼요)?\s*"
    r"(?:[1-9]\s*학년\s*)?(?:[12]\s*학기|여름\s*학기|겨울\s*학기|계절\s*학기|[1-9]\s*학년)"
    r"\s*(?:는|은|도|만|요)?\s*[?？!.\s]*$"
)


def is_procedure_question(question: str) -> bool:
    """성적 '제도·절차' 질문인가 — 개인 수강 이력으로는 답할 수 없는 질문."""
    return bool(_PROCEDURE_RE.search(question or ""))


def is_grade_fragment(question: str) -> bool:
    """'2학기는?'처럼 시점만 남은 후속 파편인가."""
    return bool(_FRAGMENT_RE.match(question or ""))


def is_my_grades_question(question: str) -> bool:
    """키워드 fast-path용 — 검색 없이 바로 개인 조회로 확정해도 되는 질문인가.

    좁게 잡는 게 원칙이다. 여기서 놓친 표현은 임베딩 라우터가 my_grades 토픽으로 받아내고,
    그 뒤 looks_personal()이 한 번 더 거른다. 좁아서 생기는 손해는 없고 넓어서 생기는 오답만 있다.
    실측: 실제 질문 2,356종 중 5종만 발동, 오탐 0.
    """
    q = question or ""
    if is_procedure_question(q) or _OTHER_DOMAIN_RE.search(q):
        return False
    has_period = bool(_PERIOD_RE.search(q))
    if _REPORT_RE.search(q):
        return has_period or bool(_FIRST_PERSON_RE.search(q))
    if _WEAK_RE.search(q):
        return has_period          # 약기 어휘는 시점이 있을 때만 (졸업요건과 어휘가 겹친다)
    return False


def looks_personal(question: str, prev_topic: str | None = None) -> bool:
    """핸들러 재검증용 — 임베딩이 여기로 보낸 질문이 정말 개인 성적표 요청인가.

    fast-path보다 한 칸 넓다(약기 어휘 + 1인칭도 인정). 임베딩이 이미 my_grades를 1등으로
    골랐다는 신호가 앞에 있기 때문이다. 대신 파편은 직전 맥락을 요구해 더 엄격하다.
    """
    q = question or ""
    if is_procedure_question(q) or _OTHER_DOMAIN_RE.search(q):
        return False
    if _FRAGMENT_RE.match(q):
        return prev_topic == "my_grades"
    if _REPORT_RE.search(q) or _WEAK_RE.search(q):
        return bool(_PERIOD_RE.search(q) or _FIRST_PERSON_RE.search(q))
    return False

_NO_DATA_GUIDE = (
    "아직 등록된 수강 이력이 없어서 성적을 알려드릴 수 없어요.\n\n"
    "**마이페이지 → 수강 이력** 탭에서 대학정보시스템의 '전체 기이수성적' 엑셀 파일을 올리면, "
    "그때부터 학기별 성적을 여기서 바로 확인하실 수 있어요."
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _season_label(word: str) -> str:
    """'계절'처럼 뭉뚱그린 표현은 어느 계절인지 특정하지 않는다(호출부가 둘 다 본다)."""
    return {"여름": "여름학기", "하계": "여름학기",
            "겨울": "겨울학기", "동계": "겨울학기"}.get(word, "")


# ── 데이터 로드 ────────────────────────────────────────────────────

async def _load_rows(db: AsyncSession, student_id: int) -> tuple[list[dict], int]:
    """수강 이력을 (학기 있는 행, 학기 없는 행 수)로 나눠 반환.

    년도가 비어 있는 행은 초기 더미 데이터라 어느 학기에도 매달 수 없다. 표에서는 빼되
    몇 건인지는 세어 두고 답변 각주로 밝힌다 — 조용히 버리면 학점이 안 맞는 것처럼 보인다.
    """
    rows = (await db.execute(
        select(StudentCourse, Course)
        .outerjoin(Course, Course.code == StudentCourse.course_code)
        .where(StudentCourse.student_id == student_id)
    )).all()

    out: list[dict] = []
    undated = 0
    for sc, c in rows:
        if sc.year is None or not sc.semester:
            undated += 1
            continue
        out.append({
            "year": int(sc.year),
            "semester": sc.semester,
            "name": (c.name if c else None) or sc.course_code,
            "category": (c.category if c else None) or "-",
            "credits": float(c.credits) if (c and c.credits is not None) else 0.0,
            "grade": sc.grade or "-",
            "point": float(sc.grade_point) if sc.grade_point is not None else None,
            "passed": bool(sc.is_passed),
        })
    return out, undated


def _build_terms(rows: list[dict]) -> list[dict]:
    """(년도, 학기)를 오래된 순으로 정렬하고 학년·학기 라벨을 붙인다.

    학년은 '이수한 학년도의 순번'이다. 등록한 해를 오래된 순으로 세어 첫 해가 1학년,
    다음 해가 2학년이 된다. 한 해 안의 1학기·2학기·계절학기는 모두 같은 학년이다.

    정규학기 개수를 2로 나누는 방식이면 안 된다. 그러면 한 학기만 이수한 해가 있을 때
    그 뒤의 학년 경계가 반 학기씩 밀려, 같은 학년도의 1학기와 2학기가 다른 학년으로 갈린다.
    실측(김철수, 2024년 1학기만 이수):
        2025년 1학기 → '2학년 2학기' / 2025년 2학기 → '3학년 1학기'
    같은 해인데 학년이 바뀌어 버렸다. 학년은 학년도 단위로 오르므로 이는 사실과 다르다.
    학년도로 세면 2025년의 두 학기가 함께 3학년이 된다.

    휴학해 등록하지 않은 해는 행이 없어 자연히 건너뛰어진다 — 학년은 등록한 해만 오른다.
    """
    keys = sorted({(r["year"], r["semester"]) for r in rows},
                  key=lambda k: (k[0], _TERM_RANK.get(k[1], 9), k[1]))

    # 등록한 학년도 → 학년. 첫 해가 1학년.
    grade_of_year = {y: i + 1 for i, y in enumerate(sorted({k[0] for k in keys}))}

    terms: list[dict] = []
    for year, sem in keys:
        grade = grade_of_year[year]
        if sem in _REGULAR_TERMS:
            no = 1 if sem == "1학기" else 2
            label = f"{grade}학년 {no}학기"
        else:
            no = None
            label = f"{grade}학년 {sem}"
        terms.append({
            "year": year, "semester": sem,
            "grade_year": grade, "term_no": no,
            "label": label,
            "full_label": f"{label} ({year}년 {sem})",
            "rows": [r for r in rows if r["year"] == year and r["semester"] == sem],
        })
    return terms


# ── 학기 선택 ──────────────────────────────────────────────────────

def _select_terms(question: str, terms: list[dict]) -> tuple[list[dict] | None, str | None]:
    """질문이 가리키는 학기 목록과, 못 찾았을 때 보여줄 요청 라벨을 반환.

    (None, None) = 학기를 특정하지 않은 질문 → 호출부가 전체 요약을 낸다.
    ([],  '3학년 2학기') = 특정했는데 그 학기 이력이 없음 → 호출부가 있는 학기를 안내한다.
    """
    q = question or ""

    m = _RE_GRADE_TERM.search(q)
    if m:
        g, t = int(m.group(1)), int(m.group(2))
        want = f"{g}학년 {t}학기"
        return [x for x in terms if x["label"] == want], want

    m = _RE_GRADE_SEASON.search(q)
    if m:
        g, season = int(m.group(1)), _season_label(m.group(2))
        want = f"{g}학년 {season or '계절학기'}"
        hit = [x for x in terms if x["grade_year"] == g and x["term_no"] is None
               and (not season or x["semester"] == season)]
        return hit, want

    m = _RE_YEAR_TERM.search(q)
    if m:
        y, t = int(m.group(1)), int(m.group(2))
        want = f"{y}년 {t}학기"
        return [x for x in terms if x["year"] == y and x["semester"] == f"{t}학기"], want

    m = _RE_YEAR_SEASON.search(q)
    if m:
        y, season = int(m.group(1)), _season_label(m.group(2))
        want = f"{y}년 {season or '계절학기'}"
        hit = [x for x in terms if x["year"] == y and x["term_no"] is None
               and (not season or x["semester"] == season)]
        return hit, want

    m = _RE_YEAR.search(q)
    if m:
        y = int(m.group(1))
        return [x for x in terms if x["year"] == y], f"{y}년"

    m = _RE_GRADE.search(q)
    if m:
        g = int(m.group(1))
        return [x for x in terms if x["grade_year"] == g], f"{g}학년"

    if _RE_PREV_TERM.search(q):
        regular = [x for x in terms if x["term_no"] is not None]
        return (regular[-2:-1] if len(regular) >= 2 else []), "지난 학기"

    if _RE_LATEST.search(q):
        return (terms[-1:] if terms else []), "가장 최근 학기"

    m = _RE_SEASON_ONLY.search(q)
    if m:
        season = _season_label(m.group(1))
        hit = [x for x in terms if x["term_no"] is None
               and (not season or x["semester"] == season)]
        return hit, season or "계절학기"

    m = _RE_TERM_ONLY.search(q)
    if m:
        # 학년 없이 '1학기'만 물으면 가장 최근의 그 학기로 본다
        # (모든 1학기를 다 펼치면 묻지 않은 학기까지 쏟아진다).
        t = f"{m.group(1)}학기"
        hit = [x for x in terms if x["semester"] == t]
        return (hit[-1:] if hit else []), t

    return None, None


def _find_courses(question: str, rows: list[dict]) -> list[dict]:
    """질문에 과목명이 들어 있으면 그 과목 수강 기록을 찾는다('자료구조 성적 몇 점이야?').

    엑셀 과목명은 공백이 없어('컴퓨터프로그래밍') 양쪽에서 공백을 지우고 비교한다.
    2글자 과목명은 '영어'·'회계'처럼 흔한 말과 겹쳐 오탐이 나므로 3글자부터만 본다.
    """
    q = _norm(question)
    hits = [r for r in rows if len(_norm(r["name"])) >= 3 and _norm(r["name"]) in q]
    # 재수강이면 같은 과목이 학기별로 여러 건 — 오래된 순으로 보여준다
    return sorted(hits, key=lambda r: (r["year"], _TERM_RANK.get(r["semester"], 9)))


# ── 표 만들기 ──────────────────────────────────────────────────────

def _cell(v: str) -> str:
    """표 셀 이스케이프 — 과목명에 '|'가 있으면 열이 통째로 밀린다."""
    return str(v).replace("|", "\\|")


def _num(v: float) -> str:
    return f"{v:g}"


def _stats(rows: list[dict]) -> tuple[float, float | None, int]:
    """(이수학점, 평점평균, 평점 없는 과목 수).

    이수학점은 통과한 과목만 센다(F는 학점으로 인정되지 않는다).
    평점평균은 평점이 있는 과목만 학점 가중으로 계산한다 — P/NP를 0으로 넣으면 평균이 무너진다.
    """
    credits = sum(r["credits"] for r in rows if r["passed"])
    graded = [r for r in rows if r["point"] is not None]
    gc = sum(r["credits"] for r in graded)
    gpa = round(sum(r["point"] * r["credits"] for r in graded) / gc, 2) if gc else None
    return credits, gpa, len(rows) - len(graded)


def _course_table(rows: list[dict]) -> list[str]:
    ordered = sorted(rows, key=lambda r: (_CATEGORY_RANK.get(r["category"], 9), r["name"]))
    lines = ["| 과목명 | 이수구분 | 학점 | 등급 | 평점 |",
             "| --- | --- | --- | --- | --- |"]
    for r in ordered:
        point = _num(r["point"]) if r["point"] is not None else "–"
        lines.append(
            f"| {_cell(r['name'])} | {r['category']} | {_num(r['credits'])} | {r['grade']} | {point} |")
    return lines


def _summary_line(rows: list[dict], prefix: str = "") -> str:
    credits, gpa, ungraded = _stats(rows)
    text = f"{prefix}이수학점 **{_num(credits)}학점**"
    if gpa is not None:
        text += f" · 평점평균 **{gpa:.2f}** / {GRADE_SCALE}"
    if ungraded:
        text += f"\n\n※ 평점이 없는 P(합격) 과목 {ungraded}개는 평점평균에서 제외했어요."
    return text


def _term_detail(term: dict) -> list[str]:
    return [f"**{term['full_label']} 성적**", "", *_course_table(term["rows"]), "",
            _summary_line(term["rows"])]


def _term_overview(title: str, terms: list[dict], undated: int = 0) -> str:
    """학기가 많을 때의 요약표 — 학기별 학점·평점만 보여주고 상세는 되묻게 한다.

    undated(년도 없는 행) 각주는 전체 조회에서만 붙인다. '1학년 성적'처럼 범위를 좁힌
    답변에 붙이면 그 학년에서 빠진 과목인 것처럼 읽힌다.
    """
    lines = [f"**{title}** (총 {len(terms)}학기)", "",
             "| 학기 | 과목 수 | 이수학점 | 평점평균 |",
             "| --- | --- | --- | --- |"]
    for t in terms:
        credits, gpa, _ = _stats(t["rows"])
        avg = f"{gpa:.2f}" if gpa is not None else "–"
        lines.append(f"| {t['full_label']} | {len(t['rows'])}과목 | {_num(credits)} | {avg} |")

    every = [r for t in terms for r in t["rows"]]
    lines += ["", _summary_line(every, prefix="합계 ")]
    if undated:
        lines.append(f"\n※ 년도·학기 정보가 없는 수강 기록 {undated}건은 표에서 제외했어요 "
                     f"(마이페이지 → 수강 이력에서 확인하실 수 있어요).")
    lines.append("\n특정 학기가 궁금하시면 `2학년 1학기 성적 알려줘`처럼 물어봐 주세요!")
    return "\n".join(lines)


def _not_found(want: str, terms: list[dict]) -> str:
    have = "\n".join(f"- {t['full_label']}" for t in terms)
    return (f"**{want}** 수강 이력은 아직 등록돼 있지 않아요.\n\n"
            f"지금 등록된 학기는 이렇게 있어요.\n{have}")


# ── 메인 진입점 ────────────────────────────────────────────────────

def _carry_over_period(question: str, prev_question: str | None) -> str:
    """'1학년 1학기 성적' 뒤의 '2학기는?'에 직전 질문의 학년(또는 년도)을 빌려준다.

    학기만 말했고 학년·년도가 없을 때만 붙인다. 조건을 이렇게 좁히지 않으면 후속으로 던진
    '내 성적 알려줘'(전체 요약을 원하는 질문)에까지 학년이 붙어 한 학년만 나온다.
    """
    if not prev_question or not question:
        return question
    if not _RE_ANY_TERM.search(question):
        return question
    if _RE_GRADE.search(question) or _RE_YEAR.search(question):
        return question
    m = _RE_GRADE.search(prev_question) or _RE_YEAR.search(prev_question)
    if not m:
        return question
    merged = f"{m.group(0)} {question}"
    print(f"[MyGrades] 후속 질문에 직전 기준 보충: '{question}' → '{merged}'")
    return merged


class MyGradesService:

    async def answer(self, question: str, student_id: int, db: AsyncSession,
                     prev_question: str | None = None,
                     prev_topic: str | None = None) -> tuple[str, dict]:
        """(답변, 메타) 반환. 메타에 fallback이 있으면 개인 데이터로 답할 질문이 아니다.

        임베딩 라우터는 '2학년은?'·'개꿀 과목'처럼 주제어가 없는 질문을 my_grades로
        확신해 버리는 일이 있다(전수 감사에서 6종 적발). 그래서 여기서 한 번 더 판정하고,
        개인 성적표 요청이 아니면 답을 만들지 않고 RAG로 넘긴다.

        prev_question은 '직전에도 성적을 물었을 때'만 넘어온다(호출부가 판단). 무관한 이전
        질문의 학년이 섞이면 묻지 않은 학기를 답하게 된다.
        """
        original = question
        rows, undated = await _load_rows(db, student_id)

        # 과목명을 직접 부른 질문('논리와프로그래밍 성적 알려줘')은 시점도 1인칭도 없지만
        # 이력에 그 과목이 있으면 명백한 개인 조회다 — 어휘 규칙의 예외로 인정한다.
        by_course = bool(rows) and bool(_find_courses(original, rows))
        if not (looks_personal(original, prev_topic) or by_course):
            return "", {"fallback": f"개인 성적표 요청으로 보기 어려움: '{original[:40]}'"}

        if not rows:
            print(f"[MyGrades] 학생 {student_id} 수강 이력 없음 → 업로드 안내")
            return _NO_DATA_GUIDE, {"source": "database", "topic": "my_grades"}

        question = _carry_over_period(original, prev_question)
        name = await db.scalar(select(Student.name).where(Student.id == student_id))
        terms = _build_terms(rows)
        meta = {"source": "database", "topic": "my_grades"}

        selected, want = _select_terms(question, terms)

        # 학기를 특정하지 않았으면, 과목명으로 물었는지 먼저 본다('자료구조 성적 몇 점이야?')
        if selected is None:
            hits = _find_courses(question, rows)
            if hits:
                print(f"[MyGrades] 과목명 매칭 {len(hits)}건 → 과목별 답변")
                lines = [f"**{_cell(hits[0]['name'])} 성적**", ""]
                for r in hits:
                    term = next((t for t in terms if t["year"] == r["year"]
                                 and t["semester"] == r["semester"]), None)
                    point = f" (평점 {_num(r['point'])})" if r["point"] is not None else ""
                    where = term["full_label"] if term else f"{r['year']}년 {r['semester']}"
                    lines.append(f"- {where} · {r['category']} {_num(r['credits'])}학점 · "
                                 f"**{r['grade']}**{point}")
                return "\n".join(lines), meta

        if selected is None:
            print(f"[MyGrades] 학기 미지정 → 전체 {len(terms)}학기 요약")
            who = f"{name}님 " if name else ""
            return _term_overview(f"{who}학기별 성적", terms, undated), meta

        if not selected:
            print(f"[MyGrades] '{want}' 이력 없음 → 등록된 학기 안내")
            return _not_found(want, terms), meta

        if len(selected) <= _MAX_DETAIL_TERMS:
            print(f"[MyGrades] '{want}' → {len(selected)}개 학기 과목표")
            blocks = ["\n".join(_term_detail(t)) for t in selected]
            return "\n\n".join(blocks), meta

        print(f"[MyGrades] '{want}' → {len(selected)}개 학기라 요약표")
        return _term_overview(f"{want} 성적", selected), meta


my_grades_service = MyGradesService()
