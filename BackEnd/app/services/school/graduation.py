

import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, distinct

from app.models.DB_Table import (
    Student, Department, Division, College, RequirementSet, RequirementRule,
    StudentAchievement, Course, StudentCourse
)
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.rag.Embedding import BaaiEmbedding, baai_embedding
from app.prompts import (
    GRADUATION_DB_PROMPT, GRADUATION_RAG_PROMPT, GRADUATION_COMBINED_PROMPT,
    GRADUATION_OTHER_DEPT_PROMPT, GRADUATION_MY_DEPT_PROMPT, WEAK_EVIDENCE_DIRECTIVE,
    GRADUATION_COHORT_DIRECTIVE,
)


# ── 학과명 매칭 (별칭 기반) ─────────────────────────────────────────
# 질문에 다른 학과가 언급됐는지 코드로 판별 (8B 판단에 맡기지 않음).
# 서버/첫 호출 시 DB에서 (id, name, aliases)를 캐시로 로드한다.
_DEPT_CACHE: list[tuple[int, str, list[str]]] | None = None
# 학부(division)명 → 소속 학과 [(dept_id, name)…]. 학부는 자체 졸업요건이 없어(요건은 학과별),
# 학부명으로 물으면 소속 학과 중 어느 곳인지 되묻는다. ('게임멀티미디어학부' → 게임소프트/게임그래픽)
_DIVISION_CACHE: list[tuple[str, list[tuple[int, str]]]] | None = None
# 단과대학(college)명 → 소속 학과 (직속 + 소속 학부의 학과). 학부와 같은 이유로 되묻기용.
# ('솔브릿지국제경영대학' → 소속 학과들). 없으면 본인 학과로 폴백돼 LLM이 창작한다(실측).
_COLLEGE_CACHE: list[tuple[str, list[tuple[int, str]]]] | None = None


# 학과명에 쓰이는 가운뎃점 변형들 — 입력기·문서마다 다른 코드포인트가 나온다.
# (DB 학과명은 U+00B7, 규정 문서는 U+2024를 쓰고, 한/글·MS Word 복붙은 U+2027,
#  일본어 IME가 켜져 있으면 U+30FB/U+FF65가 섞인다. 하나라도 빠지면 그 표기로 물었을 때
#  학과 인식이 통째로 실패하므로 비교 단계에서 모두 지운다.)
_SEP_CHARS = "·․‧・･•"          # U+00B7 U+2024 U+2027 U+30FB U+FF65 U+2022
_NORM_RE = re.compile(r"[\s" + _SEP_CHARS + r"/,]")


def _norm(s: str) -> str:
    """비교용 정규화 — 공백·가운뎃점 변형·구분자(/,) 제거 + 소문자."""
    return _NORM_RE.sub("", s or "").lower()


def reset_cache() -> None:
    """어드민에서 학과·학부·단과대를 고쳤을 때 캐시 무효화 (department.reset_cache와 짝).

    이 캐시는 첫 졸업 질문 때 1회 로드되고 그 뒤로는 갱신되지 않는다. 그동안 학과 관리
    화면은 챗봇 학과 안내 캐시만 비워서, 학부를 새로 만들어도 졸업 답변은 서버를 다시
    띄우기 전까지 옛 편제로 답했다(실측: 재활학부 신설 후 재시작 전까지 반영 안 됨).
    """
    global _DEPT_CACHE, _DIVISION_CACHE, _COLLEGE_CACHE
    _DEPT_CACHE = None
    _DIVISION_CACHE = None
    _COLLEGE_CACHE = None
    print("[Graduation] 학과·학부·단과대 캐시 무효화 — 다음 질문에서 다시 로드")


def detect_department(question: str) -> tuple[int, str] | None:
    """질문에서 학과명/별칭을 탐지해 (dept_id, name) 반환. 가장 긴 매칭 우선(부분매칭 오탐 방지).
    캐시 미로드 또는 미매칭이면 None → 호출부에서 '내 학과'로 폴백."""
    if not _DEPT_CACHE:
        return None
    q = _norm(question)
    best: tuple[int, int, str] | None = None   # (매칭길이, id, name)
    for did, name, aliases in _DEPT_CACHE:
        for term in [name, *(aliases or [])]:
            nt = _norm(term)
            if nt and nt in q and (best is None or len(nt) > best[0]):
                best = (len(nt), did, name)
    return (best[1], best[2]) if best else None


# 졸업 질문에서 학과 키워드 매칭 시 걷어낼 일반어 (이게 키워드로 남으면 전 학과가 걸린다).
_DEPT_KW_STOPWORDS = (
    "관련", "학과", "전공", "학부", "단과대학", "단과대", "대학교", "대학", "계열",
    "졸업요건", "졸업", "요건", "이수", "학점", "기준", "조건",
    "뭐가", "뭐", "무슨", "어떤", "어느", "있어요", "있나요", "있어", "있나", "있는",
    "알려줘", "알려", "소개", "정보", "대해서", "대해", "궁금", "확인",
)


def _keyword_departments(question: str) -> tuple[str, list[tuple[int, str]]]:
    """detect_department 실패 시, 일반어를 걷어낸 키워드로 관련 학과를 찾는다(부분일치).
    반환 (키워드, [(dept_id, name)…]). 없으면 ("", []).
    예: '경영학과 졸업요건' → ('경영', [(id,'AI경영학과'),(id,'철도경영학과'),…]) → 호출부가 되물음.
    """
    if not _DEPT_CACHE:
        return "", []
    q = question
    for w in _DEPT_KW_STOPWORDS:
        q = q.replace(w, " ")
    tokens = [t for t in re.findall(r"[가-힣A-Za-z]+", q) if len(t) >= 2]
    for kw in tokens:
        nkw = _norm(kw)
        if len(nkw) < 2:
            continue
        matches = {(did, name) for did, name, aliases in _DEPT_CACHE
                   if any(nkw in _norm(t) for t in [name, *(aliases or [])])}
        # 학부·단과대명이 걸리면 소속 학과로 확장 ('게임멀티미디어학부'→게임소프트/게임그래픽,
        # '솔브릿지국제경영대학'→소속 학과들). 그래야 학부/단과대로 물어도 되묻기로 이어진다.
        for group_name, members in (_DIVISION_CACHE or []) + (_COLLEGE_CACHE or []):
            if nkw in _norm(group_name):
                matches.update(members)
        if matches:
            return kw, sorted(matches, key=lambda x: x[1])
    return "", []


# '○○학과/전공/학부'처럼 특정 단위를 명시했는지 판별 — 명시했는데 못 찾으면 본인 학과로
# 폴백하지 않고 정직하게 실패시킨다(LLM이 '가장 가까운 [본인학과]'를 지어내는 것 방지).
# '우리/저희 학과'처럼 자기 학과를 가리키는 지시·소유 표현은 제외한다.
_NAMED_UNIT_RE = re.compile(r"([가-힣A-Za-z]{2,})\s*(?:학과|전공|학부)")
_UNIT_GENERIC_PREFIX = {"우리", "저희", "본인", "해당", "무슨", "어떤", "어느", "같은",
                        "다른", "이번", "모든", "졸업", "전체",
                        # 이수 '제도' 이름 — 학과명이 아니다. 빼두지 않으면 '복수+전공'이
                        # 학과 명시로 오인돼 "말씀하신 학과·학부를 찾지 못했어요"로 빠진다
                        # (실측: '복수전공 필수야?'). 다전공·부전공·주전공도 같은 층위.
                        "복수", "다", "부", "주", "심화", "연계", "융합", "자기설계"}


# 소속 학과가 없는 계정(관리자·DEV 등)이 '내 졸업요건'류를 물었을 때의 안내.
# 이 계정은 학과·입학연도가 정해지지 않아 개인 기준 답변이 원리상 불가능한데, 예전엔
# 생 RAG가 0건을 내면 "자료를 찾지 못했어요"만 나가 시스템 결함처럼 보였다(실측:
# admin 계정 '내년에 졸업하려면 뭐 필요해?' → 못 찾음. 같은 질문이 학생 계정에선 정상).
_NO_DEPT_GUIDE = (
    "이 계정에는 소속 학과 정보가 없어서 '내 졸업요건'은 안내해 드릴 수 없어요.\n\n"
    "학과를 함께 알려주시면 그 학과 기준으로 안내해 드릴게요. "
    "(예: `간호학과 졸업요건`, `2025학번 컴퓨터공학전공 졸업요건`)"
)
# 졸업 경로의 '못 찾음' 응답 판별용
_GRAD_NOT_FOUND_MARKERS = ("찾지 못", "찾을 수 없", "제공된 문서에", "관련 자료가 없")

# 1인칭으로 '자기 현황'을 묻는 표현 — '내 학점', '제가 졸업 가능한가요' 등.
# '내년'·'안내'·'내용'처럼 다른 낱말 속의 '내'는 걸리지 않도록 앞뒤를 좁게 제한한다.
_OWN_STATUS_RE = re.compile(r"(?:^|\s)(?:내|제|저|나)(?:\s|가|는|의|를)|본인|내가|제가|나의")


def _ensure_fallback_notice(answer: str, requested_year: int, actual_year: int,
                            is_fallback: bool) -> str:
    """대체 연도로 답했으면 그 사실을 반드시 첫 줄에 남긴다(코드로 확정).

    프롬프트에도 같은 지시가 있지만 LLM이 낮은 확률로 빠뜨린다(실측: '2029학년도 간호학과
    졸업요건' 8회 중 7회는 고지했는데 1회 누락 → 사용자에겐 2026년 요건이 2029년 것처럼 보임).
    요청 연도와 실제 연도가 다르다는 건 코드가 이미 아는 사실이므로, LLM 재량에 맡기지 않는다.
    이미 LLM이 요청 연도를 언급했으면 중복으로 붙이지 않는다.
    """
    if not is_fallback or actual_year == requested_year or not answer:
        return answer
    if str(requested_year) in answer:      # LLM이 이미 밝힘
        return answer
    print(f"[Graduation] 폴백 고지 누락 감지 → 코드로 첨부 ({requested_year}→{actual_year})")
    return (f"{requested_year}년 졸업요건은 아직 등록되어 있지 않아, "
            f"가장 가까운 {actual_year}학번 기준으로 안내해 드릴게요.\n\n{answer}")


def _ensure_year_notice(answer: str, actual_year: int) -> str:
    """어느 학번 기준으로 답했는지 반드시 남긴다(코드로 확정).

    졸업요건은 학과×입학연도로 값이 갈린다(실측: AI·컴퓨터공학과 2024학번 전공65/교양37,
    2025학번부터 전공62/교양34). 그런데 답변에 기준 연도가 없으면 학생은 그것이 자기 학번
    기준이라고 읽는다 — 특히 '다른 학과'를 물으면 그 학과의 최신 연도로 답하도록 되어 있어
    (_answer_dept_requirement 호출부 참고) 24학번 학생이 2025학번 요건을 자기 것으로 오해한다.

    연도는 req_context에 '(NNNN학번 기준)'으로 이미 넣어 주는데도 LLM이 답변에서 빠뜨린다.
    프롬프트가 연도 언급을 '필요할 때만'으로 열어 둔 탓인데, 그 조항은 LLM이 "요청한 연도가
    없어 대신 안내한다"는 거짓 폴백 문구를 지어내던 문제를 막으려고 넣은 것이라 되돌리기 어렵다.
    → 어느 연도로 답했는지는 코드가 이미 아는 사실이므로 LLM 재량에 맡기지 않는다
      (_ensure_fallback_notice와 같은 방식).

    이미 그 연도가 답변에 있으면(LLM이 밝혔거나 폴백 고지가 붙었으면) 덧붙이지 않는다.
    """
    if not answer or not actual_year or str(actual_year) in answer:
        return answer
    return f"{actual_year}학번 기준 졸업요건이에요.\n\n{answer}"


def _named_unresolved_unit(question: str) -> bool:
    for m in _NAMED_UNIT_RE.finditer(question or ""):
        if m.group(1) not in _UNIT_GENERIC_PREFIX:
            return True
    return False


# 자격증 초점 질문('자격증 뭐 딸 수 있어?')일 때 졸업 답변을 자격증 중심으로 재배치하는 특별지시.
# 코퍼스에 '취득 가능 자격증 목록' 문서가 없어, 구체 목록 대신 '어디서 확인하는지'를 안내한다(정직).
# 자격증 언급이 없는 일반 졸업 질문에는 주입하지 않아 기존 답변에 영향이 없다.
_CERT_FOCUS_DIRECTIVE = (
    "[특별지시] 이 질문은 '자격증'에 초점이 있다. 반드시 아래 순서로 답하라:\n"
    "1) 전공 관련 자격증 요건(예: 전공 관련 자격증 몇 개 이상 취득 필요 등)을 맨 앞에 안내한다.\n"
    "2) 구체적인 자격증 종류는 '학과 사무실·홈페이지·게시판' 또는 '교양 특별시험 학점인정 안내'에서 "
    "확인하도록 안내를 덧붙인다.\n"
    "3) 학점 기준·본인 이수현황은 그 뒤에 간단히만 정리한다.\n"
    "아래 기본 규칙은 위 순서와 충돌하지 않는 선에서 따른다.\n\n"
)


# 질문에 명시된 입학연도(학번) 탐지 — 학과와 같은 원리로 '명시되면 그 기준, 없으면 내 학번'.
# 요건은 학과 × 입학연도로 DB에 있으므로(43학과 × 2020~2026), 연도를 못 읽으면 남의 학번을
# 물어도 내 학번 요건이 나온다("2025학년도 컴퓨터공학과 졸업요건"인데 2022 기준 답변).
#   지원 표기: '2025학번', '2025학년도', '25학번', '25학년도 입학'
# 19xx도 받는다. 20\d{2}만 보던 때는 '1999학번 졸업요건'이 '연도 미언급'으로 처리돼
# 내 학번(2024) 요건이 1999년 것인 양 그대로 안내됐다 — 없는 연도라는 고지도 못 나갔다(실측).
_YEAR_4_RE = re.compile(r"((?:19|20)\d{2})\s*(?:학번|학년도)")
_YEAR_2_RE = re.compile(r"(?<!\d)(\d{2})\s*학번")
# 명시적으로 언급된 '졸업 목표 연도'("2029년 졸업", "2029년도 2월 졸업 예정") — 엄밀히는 학번이
# 아니지만 사용자가 그 연도 기준 요건을 물은 것으로 보고 '대상 연도'로 삼는다. 학번/학년도가
# 있으면 그쪽이 우선(자기 코호트를 명시한 것). 등록 안 된 미래 연도면 리졸버가 가장 가까운
# 연도로 폴백하고 그 사실을 답변에 고지한다("2029년 졸업요건은 없어 2026년 기준으로 안내").
_YEAR_GRAD_RE = re.compile(r"(20\d{2})\s*년도?\s*(?:2월\s*)?졸업")
# 마지막 폴백 — '학번/학년도/졸업'이 안 붙고 연도만 쓴 표기('2009년 간호학과 졸업요건').
# _YEAR_GRAD_RE는 연도 '바로 뒤'에 졸업이 와야 잡히는데, 사이에 학과명이 끼면 놓친다.
# 그러면 '연도 미언급'으로 처리돼 최신 연도 요건을 요청 연도인 양 답하고, 없는 연도라는
# 고지도 안 나간다(실측: '2009년 간호학과 졸업요건' → "2026학번 기준" 안내, 폴백문구 없음).
_YEAR_BARE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*년")

# 2자리 학번의 세기 판정 경계. '25학번'=2025 / '99학번'=1999.
# 없을 때는 무조건 2000을 더해 '99학번'이 2099(미래)로 읽혔다 — 미등록 미래 연도라
# 폴백은 걸리지만 고지 문구에 엉뚱한 연도가 찍힌다.
_YY_CENTURY_SPLIT = 50

# 입학연도에 따라 값이 갈리는 규정 — 이런 질문은 검색어에 학번을 붙여 해당 코호트 표를 끌어온다.
# (아무 질문에나 붙이면 리랭커 점수가 흔들려 멀쩡한 절차 질문까지 망가진다)
_COHORT_SENSITIVE_RE = re.compile(r"수료|편입|경과조치|학번별|입학연도별|입학년도별")

# 수료기준 전용 보조검색 — 구간별 표가 본문·부칙에 흩어져 있어 일반 검색으로는 질문 표현에
# 따라 한 구간만 잡히거나 아예 안 잡힌다(실측: '학년별 수료 기준 알려줘' → 34~67 표 미포함,
# 결국 "확인 못 함"으로 끝남). 규정 문서로 범위를 좁혀 '수료기준' 한 단어로 재검색하면
# 청크 18·20·7·11이 함께 잡혀 모든 구간 표가 확보된다(실측).
_COMPLETION_RE = re.compile(r"수료")
_COMPLETION_SRC = "졸업종합시험_및_졸업에_관한_규정"


def detect_admission_year(question: str) -> int | None:
    """질문에 명시된 '요건 기준 연도'를 탐지. 없으면 None → 호출부에서 '내 학번'으로 폴백.

    우선순위: 학번/학년도(자기 코호트 명시) > 2자리 학번 > 졸업 목표 연도.
    """
    if not question:
        return None
    m = _YEAR_4_RE.search(question)
    if m:
        return int(m.group(1))
    m = _YEAR_2_RE.search(question)
    if m:
        yy = int(m.group(1))            # '25학번' → 2025 / '99학번' → 1999
        return (1900 if yy >= _YY_CENTURY_SPLIT else 2000) + yy
    m = _YEAR_GRAD_RE.search(question)
    if m:
        return int(m.group(1))          # '2029년 졸업' → 2029 (없으면 리졸버가 폴백+고지)
    m = _YEAR_BARE_RE.search(question)
    if m:
        return int(m.group(1))          # '2009년 …' → 2009 (미등록이면 리졸버가 폴백+고지)
    return None

# ── 졸업 질문 유형 분류 프로토타입 (임베딩 기반) ──────────────────────
# personal : 개인 현황 조회 (DB)
# document : 공식 절차/일정 조회 (RAG)
# both     : 졸업요건 일반 질문 (DB + RAG)
_GRADUATION_PROTOTYPES: dict[str, list[str]] = {
    "personal": [
        "내 졸업학점이 얼마나 남았나요?",
        "제 이수현황을 알고 싶어요",
        "저 졸업 가능한가요?",
        "내가 전공 학점이 몇 점 남았어요?",
        "나는 교양 이수가 충분한가요?",
        "제 졸업요건 충족 여부 알려주세요",
        "저의 졸업 상태를 확인해주세요",
    ],
    "document": [
        "졸업 신청 방법이 어떻게 되나요?",
        "졸업 서류 제출 절차가 어떻게 되나요?",
        "졸업사정 일정이 언제예요?",
        "졸업 신청 기간이 언제인가요?",
        "졸업 신청은 어디서 하나요?",
        "졸업 관련 규정을 알고 싶어요",
        # 편입생·학번별 요건은 '내 현황'(personal/both)이 아니라 '규정 정보' 조회다.
        # both로 가면 _answer_my_dept가 학생 학과 기준으로만 검색해(RAG 쿼리 고정) 편입생·학번
        # 문서를 못 찾고 개인 학점현황만 섞여 나온다. document로 보내 원본 질문으로 RAG 검색시킨다.
        "편입생은 몇 학점을 이수해야 하나요?",
        "편입생 졸업 이수학점 기준이 어떻게 되나요?",
        "2025학번 교양 이수학점 기준을 알려주세요",
        "학번별 졸업 이수학점 기준이 궁금해요",
        "2020학번 교양 몇 학점 들어야 하나요?",
        "몇 학번은 교양 몇 학점 들어야 해요?",
        # 다전공·복수전공·부전공 '의무 여부'는 학칙 제30조의2 / 졸업규정 제20조의2 조회다.
        # both로 가면 _answer_my_dept가 학점 요건표+개인 현황을 통째로 쏟아내 정작 '의무인지'에
        # 답하지 않는다(실측: '다전공 꼭 들어야 해?' → 졸업요건 전체 덤프).
        "다전공을 꼭 이수해야 하나요?",
        "다전공 의무 이수 대상이 누구인가요?",
        "복수전공은 필수인가요?",
        "부전공 이수 규정이 어떻게 되나요?",
        "다전공 이수가 면제되는 경우가 있나요?",
        # 학년별 수료기준도 '내 현황'이 아니라 규정(졸업규정 제21조·부칙) 조회다. 게다가 입학연도별로
        # 기준이 달라(2026~ / 2019~2024 / 2018 이전) 개인 학점현황을 섞으면 오해를 부른다.
        # 실측: '1학년 수료 기준 학점이 뭐야?' → both로 빠져 졸업요건 전체가 덤프됐다.
        "수료 기준이 어떻게 되나요?",
        "1학년 수료 기준 학점이 몇 학점인가요?",
        "학년별 수료 학점 기준을 알려주세요",
        "몇 학점을 취득해야 다음 학년으로 수료되나요?",
        "수료와 졸업은 어떻게 다른가요?",
    ],
    "both": [
        "졸업하려면 학점이 몇 점 필요해요?",
        "졸업요건이 어떻게 되나요?",
        "전공필수를 다 들어야 졸업할 수 있나요?",
        "교양필수 학점이 몇 학점이에요?",
        "이수조건을 알고 싶어요",
        "영어 인증이 졸업에 필요한가요?",
        "졸업까지 뭘 더 들어야 하나요?",
    ],
}


# 유형 분류 점수 = 카테고리 프로토타입 중 질문과 가장 가까운 상위 K개의 평균 유사도.
# (평균 프로토타입은 "졸업요건 어떻게 되니?" 같은 혼합 표현을 오분류 → top-K로 완화.
#  topic_router와 동일 원리.)
_GRAD_TOP_K = 3


class _GraduationClassifier:
    """졸업 질문 유형 임베딩 분류기 (personal / document / both)"""

    def __init__(self):
        self._embedding: BaaiEmbedding | None = None
        self._proto_vecs: dict[str, list[list[float]]] | None = None   # 카테고리별 개별 문장 벡터

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = baai_embedding   # 전역 싱글턴 공유 (모델 1회 로드)
        return self._embedding

    def _warmup(self) -> None:
        categories = list(_GRADUATION_PROTOTYPES.keys())
        all_sentences: list[str] = []
        ranges: list[tuple[int, int]] = []
        for cat in categories:
            start = len(all_sentences)
            all_sentences.extend(_GRADUATION_PROTOTYPES[cat])
            ranges.append((start, len(all_sentences)))

        all_vecs = self.embedding.embed_texts(all_sentences)
        self._proto_vecs = {}
        for cat, (start, end) in zip(categories, ranges):
            self._proto_vecs[cat] = all_vecs[start:end]   # 개별 문장 벡터 보관 (평균 안 함)
        print(f"[GraduationClassifier] {len(categories)}개 유형 임베딩 완료")

    def classify(self, question: str) -> str:
        if self._proto_vecs is None:
            self._warmup()

        q_vec = self.embedding.embed_text(question)
        best_cat, best_score = "both", -1.0
        for cat, vecs in self._proto_vecs.items():
            # 개별 문장 유사도 중 상위 K개 평균 (평균 프로토타입 대신)
            sims = sorted((sum(x * y for x, y in zip(q_vec, v)) for v in vecs), reverse=True)
            k = min(_GRAD_TOP_K, len(sims))
            score = sum(sims[:k]) / k
            if score > best_score:
                best_score, best_cat = score, cat

        print(f"[GraduationClassifier] 유형 분류 → {best_cat} ({best_score:.3f})")
        return best_cat


_graduation_classifier = _GraduationClassifier()


class GraduationService:

    # =============================================
    # 메인 진입점
    # =============================================

    async def answer_graduation_with_metadata(self, question: str, student_id: int | None, db: AsyncSession) -> tuple[str, dict]:
        """Agent가 호출하는 메인 함수 — 개인현황/문서/다른학과를 코드로 분기.

        student_id=None 은 비로그인(게스트). 아래 '학생 레코드 없음' 분기가 그대로 받아
        학과가 명시된 요건 질문에는 답하고, 1인칭 개인 현황 질문만 걸러 낸다.

        - 질문에 '내 학과가 아닌 다른 학과'가 언급되면 → 그 학과 요건(DB, 내 입학연도 기준)
          + RAG. 본인 이수현황은 절대 섞지 않는다(환각 방지).
        - 그 외: 유형 분류(personal/document/both)로 개인현황(DB)+문서(RAG) 라우팅.
        """
        await self._ensure_dept_cache(db)
        student, my_dept_name = await self._get_student(db, student_id)
        if not student:
            # 학생 레코드가 없는 계정(관리자/DEV 등)이라도 '특정 학과 졸업요건'은 답할 수 있다 —
            # 요건은 학과×연도 기준이라 개인 이수현황이 필요 없다. 학과가 잡히면 그 요건을(연도
            # 미언급 시 그 학과 최신 연도 기준), 학과가 안 잡히면 기존 생 RAG로 폴백한다.
            # (없으면 '컴퓨터 공학과 졸업요건'이 학과 탐지를 건너뛰고 생 RAG로 새 0건 → '못 찾음')
            mentioned = detect_department(question)
            if mentioned:
                year = detect_admission_year(question) or await self._latest_year(db, mentioned[0])
                if year:
                    return await self._answer_dept_requirement(question, mentioned[0], mentioned[1], year, db)
            # 1인칭 개인 현황 질문은 이 계정으로 답이 나올 수 없다 — 학과·학번이 없어 기준이
            # 정해지지 않는다. RAG로 내려보내면 검수 FAQ가 유사도만으로 가로채 엉뚱한 답을 낸다
            # (실측: admin '내 졸업학점 얼마나 남았어?' → 근거약함 게이트가 학점포기 FAQ를
            # 0.711로 물어와 "학점 포기는 최대 9학점…"을 verbatim으로 냈다).
            # 학생 계정은 이 분기 자체를 지나지 않으므로 일반 사용자 답변에는 영향이 없다.
            if _OWN_STATUS_RE.search(question) and await self._classify_question(question) == "personal":
                print("[Graduation] 학과 없는 계정 + 개인 현황 질문 → 계정 안내")
                return _NO_DEPT_GUIDE, {"source": "database", "source_file": None,
                                        "topic": "graduation", "url": None}

            # 학과 미언급 → 생 RAG. 절차·규정 질문('졸업 신청 방법')은 여기서 정상 처리된다.
            # 다만 '내 졸업요건'류는 이 계정으로 답이 나올 수 없다. RAG까지 0건이면 '자료가 없다'가
            # 아니라 '이 계정에 학과 정보가 없다'고 정확히 알려 원인을 찾을 수 있게 한다.
            answer, meta = await self._answer_from_rag(question)
            if any(m in answer for m in _GRAD_NOT_FOUND_MARKERS):
                print("[Graduation] 학과 없는 계정 + RAG 0건 → 계정 안내로 대체")
                return _NO_DEPT_GUIDE, meta
            return answer, meta
        try:
            my_year = int(student.student_no[:4])
        except (ValueError, TypeError, IndexError):
            my_year = 2026

        mentioned = detect_department(question)
        # 정확 매칭 실패 시 키워드로 해석 — 사용자가 명시한 학과(예: '경영학과')를 본인 학과로
        # 착각해 엉뚱한 요건을 답하던 문제 방지. 1개면 그 학과로, 여러 개면 어떤 학과인지 되묻는다.
        if mentioned is None:
            kw, cands = _keyword_departments(question)
            if len(cands) == 1:
                mentioned = cands[0]
                print(f"[Graduation] 키워드 '{kw}' → 유일 학과 '{cands[0][1]}'")
            elif len(cands) >= 2:
                names = ", ".join(n for _i, n in cands)
                print(f"[Graduation] 키워드 '{kw}' → 학과 {len(cands)}개 모호 → 특정 요청")
                return (
                    f"'{kw}' 관련 학과가 여러 개라 하나로 특정하지 못했어요. "
                    f"어떤 학과의 졸업요건이 궁금하신가요?\n\n{names}",
                    {"source": "database", "source_file": None, "topic": "graduation", "url": None},
                )
            elif _named_unresolved_unit(question):
                # 특정 학과·학부를 명시했는데 못 찾음 → 본인 학과로 폴백하면 LLM이 '가장 가까운
                # [본인학과]'를 지어낸다(실측). 정직하게 못 찾음으로 안내한다.
                print("[Graduation] 명시 학과·학부 미해결 → 찾지 못함(본인 학과 폴백 금지)")
                return (
                    "말씀하신 학과·학부를 찾지 못했어요. 학과 이름을 정확히 알려주시면 "
                    "졸업요건을 안내해 드릴게요.",
                    {"source": "database", "source_file": None, "topic": "graduation", "url": None},
                )
        is_other = bool(mentioned and mentioned[0] != student.dept_id)
        # 질문에 학번이 명시되면 그 연도 요건으로 답한다(요건은 학과×입학연도로 다르다).
        mentioned_year = detect_admission_year(question)
        is_other_year = bool(mentioned_year and mentioned_year != my_year)
        target_year = mentioned_year or my_year
        print(f"[Graduation] 분기 판별: 언급학과={mentioned}, 내학과id={student.dept_id}, 다른학과={is_other}, "
              f"언급학번={mentioned_year}, 내학번={my_year}, 다른학번={is_other_year}")

        # 다른 학과 또는 다른 학번 → 그 기준의 요건만 (개인 이수현황은 '내 학과·내 학번'에서만
        # 의미가 있으므로 제외한다. 2025학번 요건에 2022학번인 내 현황을 섞으면 오해를 부른다)
        if is_other or is_other_year:
            dept_id = mentioned[0] if mentioned else student.dept_id
            dept_name = mentioned[1] if mentioned else my_dept_name
            dept_year = target_year
            # 다른 학과를 '연도 명시 없이' 물어도 '내 입학연도' 기준으로 답한다.
            #
            # 전에는 그 학과의 최신 요건 연도를 썼다. 이유는 "내 2024학번을 남의 학과에
            # 들이대면 그 학과에 2024 요건이 없을 때 '요청하신 2024년 없음 → 가장 가까운
            # 연도로 대신 안내' 같은 혼란스러운 폴백 문구가 뜬다"였는데, 그 전제가 더 이상
            # 성립하지 않는다 — 요건이 등록된 40개 학과가 모두 2020~2026을 빠짐없이 갖고 있어
            # 폴백이 발생할 수 없다(실측: 연도 범위가 다른 학과 0개).
            #
            # 반면 최신 연도로 답할 때의 피해는 실제로 발생했다: 2024학번 학생이 다른 학과를
            # 물으면 2025학번 요건(전공62/교양34)이 나오는데, 전과를 해도 졸업요건은 입학연도를
            # 따라가므로 그 학생에게 해당하지 않는 숫자다(실측 제보).
            #
            # 학생 레코드가 없는 계정(관리자 등)은 학번 자체가 없어 위쪽 분기에서 여전히
            # 최신 연도를 쓴다 — 거기서는 기준을 정할 다른 방법이 없다.
            return await self._answer_dept_requirement(question, dept_id, dept_name, dept_year, db)

        # 내 학과(또는 학과 미언급) → 유형 분류로 라우팅
        cat = await self._classify_question(question)
        if cat == "document":
            # 절차/일정 질문 → RAG. 학번을 함께 넘겨, 입학연도별로 갈리는 규정(수료기준 등)에서
            # 이 학생에게 해당하는 구간을 고르게 한다(질문에 연도가 명시되면 그쪽이 우선).
            return await self._answer_from_rag(question, cohort_year=target_year)
        # personal / both → 내 학과 졸업요건(학점+서술형) + 본인 학점 이수현황을 함께
        # (요건/현황 분류가 표현 겹침으로 불안정 → 둘 다 보여줘 분류 어려움을 우회)
        # target_year는 여기선 항상 my_year와 같다(다르면 위 분기로 빠짐) — 의도를 드러내려 통일.
        return await self._answer_my_dept(question, student.dept_id, my_dept_name, target_year, student_id, db)

    async def _ensure_dept_cache(self, db: AsyncSession) -> None:
        """학과·학부·단과대 매칭 캐시 지연 로드 (첫 졸업 질문 시 1회)."""
        global _DEPT_CACHE, _DIVISION_CACHE, _COLLEGE_CACHE
        if _DEPT_CACHE is None:
            depts = (await db.execute(select(
                Department.id, Department.name, Department.aliases,
                Department.college_id, Department.division_id,
            ))).all()
            _DEPT_CACHE = [(d[0], d[1], d[2] or []) for d in depts]

            # 학부(division) → 소속 학과. 학부/단과대명으로 물으면 소속 학과로 되묻기 위해 로드한다.
            divs = (await db.execute(select(Division.id, Division.name, Division.college_id))).all()
            div_college = {d[0]: d[2] for d in divs}   # division_id → college_id
            _DIVISION_CACHE = []
            for div_id, div_name, _cid in divs:
                members = [(d[0], d[1]) for d in depts if d[4] == div_id]
                if members:
                    _DIVISION_CACHE.append((div_name, members))

            # 단과대학(college) → 소속 학과 (직속 college_id 일치 + 소속 학부의 학과)
            cols = (await db.execute(select(College.id, College.name))).all()
            _COLLEGE_CACHE = []
            for cid, cname in cols:
                members = sorted(
                    {(d[0], d[1]) for d in depts if d[3] == cid or div_college.get(d[4]) == cid},
                    key=lambda x: x[1],
                )
                if members:
                    _COLLEGE_CACHE.append((cname, members))

            print(f"[Graduation] 캐시 로드 — 학과 {len(_DEPT_CACHE)} / 학부 "
                  f"{len(_DIVISION_CACHE)} / 단과대 {len(_COLLEGE_CACHE)}")

    async def _answer_dept_requirement(self, question: str, dept_id: int, dept_name: str,
                                       admission_year: int, db: AsyncSession) -> tuple[str, dict]:
        """학과 졸업요건 답변 (본인/타 학과 공통) — 그 학과 요건 수치(DB) + 서술형 규정(RAG).
        개인 이수현황은 미포함. '요건' 질문(both) 및 '다른 학과' 질문에 사용."""
        from pathlib import Path
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer

        rule, actual_year, is_fallback = await self._resolve_requirement_rule(db, dept_id, admission_year)
        if rule:
            fallback_note = (
                f"※ 요청하신 {admission_year}년 졸업요건은 등록돼 있지 않습니다. "
                f"가장 가까운 {actual_year}년 졸업요건으로 대신 안내합니다.\n"
            ) if (is_fallback and actual_year != admission_year) else ""
            req_context = (
                fallback_note +
                f"학과: {dept_name} ({actual_year}학번 기준)\n"
                f"전공 최소 이수학점: {rule.min_credits_major}학점\n"
                f"교양 최소 이수학점: {rule.min_credits_liberal}학점\n"
                f"졸업 총 이수학점: {rule.min_credits_total}학점\n"
                f"영어 공인성적: 필요"
            )
        else:
            req_context = f"{dept_name} {admission_year}학번 졸업요건 정보가 DB에 등록되어 있지 않습니다."

        # RAG(서술형 규정) 검색은 회화체·이전맥락이 낀 원 질문 대신 '학과 키워드'로 리랭킹한다.
        # (리랭커는 쿼리 노이즈에 극도로 민감 — "간호학과 졸업요건"=0.77 vs "…알려줘+맥락"=0.13)
        # 쿼리는 '학과명 + 졸업요건'까지만. 일반어를 덧붙이면 리랭커 점수가 무너진다
        # (실측: '컴퓨터공학전공 졸업요건'=0.860 → '…전공 교양 이수학점' 추가 시 0.121로 폭락 → 0건).
        rag_query = f"{dept_name} 졸업요건"
        rag_context, metadata = await self._search_rag(rag_query)

        # DB 요건도 없고 서술형 문서도 0건 = 이 학과에 대해 아는 게 없다. 그대로 LLM에 넘기면
        # 없는 학점·TOEIC 점수를 창작한다(메모리 기록: 호텔경영학과 사례). LLM을 건너뛴다.
        if rule is None and metadata.get("rag_empty"):
            print(f"[Graduation] ⚠️ '{dept_name}' DB요건·문서 모두 없음 → LLM 스킵(환각 방지)")
            return (
                f"죄송해요, {dept_name}의 졸업요건 자료를 찾지 못했어요. "
                "학과 사무실이나 학교 홈페이지에서 확인해 주세요.",
                metadata,
            )
        # 요건 수치(DB)는 있는데 서술형 문서만 0건이면, '못 찾음' 문자열이 컨텍스트로 들어가
        # LLM이 서술형 규정을 창작할 수 있다. 학점 기준만 쓰도록 명시적 '없음' 신호로 바꾼다.
        if metadata.get("rag_empty"):
            rag_context = "(서술형 졸업규정 문서 없음 — 위 학점 기준 외에는 추측하지 말 것)"

        prompt = GRADUATION_OTHER_DEPT_PROMPT.format(
            dept=dept_name, req_context=req_context, rag_context=rag_context, question=question,
        )
        if "자격증" in question:                 # 자격증 초점 → 자격증 중심으로 재배치
            prompt = _CERT_FOCUS_DIRECTIVE + prompt
        # 구조적 졸업 답변은 실행마다 흔들리면 안 되므로 결정론적으로(temp 0.0) 생성.
        # (0.3에서 '학점 기준' 섹션이 통째로 누락되는 변덕이 관측됨)
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)
        result = clean_answer(result)
        result = _ensure_fallback_notice(result, admission_year, actual_year, is_fallback)
        result = _ensure_year_notice(result, actual_year)

        # 파일 제안은 '완성된 답변' 기준(질문 기준은 신호가 약함). graduation은 현재 파일이 없어
        # 결과가 늘 비지만, 파일이 추가되면 자동으로 동작한다.
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, result, AVAILABLE_FILES.get("graduation", [])
        )
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def _answer_my_dept(self, question: str, dept_id: int, dept_name: str,
                             admission_year: int, student_id: int, db: AsyncSession) -> tuple[str, dict]:
        """내 학과 졸업 답변 — 졸업요건(학점 DB + 서술형 문서) + 본인 '학점' 이수현황을 함께.
        영어·자격증·토익·졸업가능여부는 현황으로 판단 안 하고 요건 안내에만 포함(DB 미추적)."""
        from pathlib import Path
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer

        # 1) 요건 학점 (DB rule) — 내 학번 요건이 없으면 가장 가까운 연도로 폴백
        rule, actual_year, is_fallback = await self._resolve_requirement_rule(db, dept_id, admission_year)
        if rule:
            fallback_note = (
                f"※ 요청하신 {admission_year}년 졸업요건은 등록돼 있지 않습니다. "
                f"가장 가까운 {actual_year}년 졸업요건으로 대신 안내합니다.\n"
            ) if (is_fallback and actual_year != admission_year) else ""
            req_context = (
                fallback_note +
                f"전공 최소 이수학점: {rule.min_credits_major}학점\n"
                f"교양 최소 이수학점: {rule.min_credits_liberal}학점\n"
                f"졸업 총 이수학점: {rule.min_credits_total}학점\n"
                f"영어 공인성적: 필요"
            )
        else:
            req_context = f"{dept_name} {admission_year}학번 졸업요건 정보가 DB에 등록되어 있지 않습니다."

        # 2) 서술형 요건 (리랭커 노이즈 방지 위해 깔끔한 학과 키워드로 검색)
        # '전공 교양 이수학점'을 붙이면 리랭커가 학과 특이성을 잃어 0건이 된다(위 _answer_dept_requirement 주석 참조).
        rag_context, metadata = await self._search_rag(f"{dept_name} 졸업요건")
        # 서술형 문서가 0건이면 '못 찾음' 문자열이 컨텍스트로 들어가 LLM이 서술형 규정을
        # 창작한다. 이 경로는 학점 요건(DB)·개인 현황이 유효하므로 LLM은 호출하되(그 수치는
        # 보여줘야 한다), 서술형 부분만 명시적 '없음' 신호로 눌러 창작을 막는다.
        # (학과명 빼고 공통 문서로 폴백하는 방식은 편입생 이수학점표가 딸려와 '나 졸업 가능해?'에
        #  안 물어본 편입 정보가 가득 나오는 부작용이 있어 롤백했다 — 정확성 우선.)
        if metadata.get("rag_empty"):
            rag_context = "(서술형 졸업규정 문서 없음 — 위 학점 기준·이수현황 외에는 추측하지 말 것)"

        # 3) 본인 '학점' 이수현황 (영어·졸업가능여부 등은 제외)
        report = await self._check_graduation_status(db, student_id)
        if "error" in report:
            status_context = report["error"]
        else:
            mj = max(0, report["req_major"] - report["earned_major"])
            lb = max(0, report["req_liberal"] - report["earned_liberal"])
            tt = max(0, report["total_required"] - report["total_earned"])
            status_context = (
                f"전공: {report['earned_major']} / {report['req_major']} (부족 {mj})\n"
                f"교양: {report['earned_liberal']} / {report['req_liberal']} (부족 {lb})\n"
                f"총: {report['total_earned']} / {report['total_required']} (부족 {tt})"
            )

        prompt = GRADUATION_MY_DEPT_PROMPT.format(
            dept=dept_name, req_context=req_context, rag_context=rag_context,
            status_context=status_context, question=question,
        )
        if "자격증" in question:                 # 자격증 초점 → 자격증 중심으로 재배치
            prompt = _CERT_FOCUS_DIRECTIVE + prompt
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)
        result = clean_answer(result)
        result = _ensure_fallback_notice(result, admission_year, actual_year, is_fallback)
        result = _ensure_year_notice(result, actual_year)

        # 파일 제안은 '완성된 답변' 기준. graduation은 현재 파일이 없어 결과가 늘 빈다.
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, result, AVAILABLE_FILES.get("graduation", [])
        )
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def answer_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        answer, _ = await self.answer_graduation_with_metadata(question, student_id, db)
        return answer

    async def get_status_answer(self, student_id: int, db: AsyncSession) -> str:
        """명시적 '내 졸업 현황' 조회 — 버튼/메뉴에서 호출. 로그인 학생 본인 학과 기준.

        채팅 분류기를 거치지 않으므로 다른 학과 질문과 섞이지 않는다.
        """
        return await self._answer_from_db("내 졸업 요건 충족 현황을 알려줘", student_id, db)

    async def get_status_report(self, current_user: Student, db: AsyncSession) -> dict:
        """학점 진행률 위젯용 — 이수/필요/남은 학점(구조화 데이터, LLM 미사용).

        백분율·졸업시험·영어인증 등은 제외하고 순수 학점만 반환한다
        (위젯이 '학점 진행률'로만 표기 — 졸업 전체 충족과 혼동 방지).
        학생이 아니거나 데이터 없음/오류면 위젯 숨김 신호({available: False})를 반환한다
        (사이드바가 깨지지 않도록 예외를 밖으로 던지지 않음)."""
        # 학생이 아니면(관리자 등) 학점 데이터 없음 → 위젯 숨김
        if getattr(current_user, "role", None) != "student":
            return {"available": False, "reason": "not_student"}
        try:
            report = await self._check_graduation_status(db, current_user.id)
        except Exception:
            import traceback
            traceback.print_exc()
            return {"available": False}
        if "error" in report:
            return {"available": False}
        remaining = max(0, report["total_required"] - report["total_earned"])
        categories = [
            {"name": "전공", "earned": report["earned_major"],   "required": report["req_major"]},
            {"name": "교양", "earned": report["earned_liberal"], "required": report["req_liberal"]},
        ]
        # 일반(일반선택): 최소 요건이 없으면(required=0) '0/0 충족'처럼 무의미하게 보임 →
        # 이수 학점이 있거나 요건이 있을 때만 항목 표시. (이수 학점은 총 이수학점엔 이미 포함)
        if report["earned_general"] > 0 or report["req_general"] > 0:
            categories.append(
                {"name": "일반", "earned": report["earned_general"], "required": report["req_general"]}
            )
        # 트랙(다전공): 트랙 요건이 있는 학과만 표시 (전공·교양과 나란한 독립 이수구분)
        if report.get("req_track") is not None:
            categories.append(
                {"name": "트랙", "earned": report["earned_track"], "required": report["req_track"]}
            )
        return {
            "available": True,
            "dept_name": report.get("dept_name"),
            "total_earned": report["total_earned"],
            "total_required": report["total_required"],
            "remaining": remaining,
            "categories": categories,
            "student_no": current_user.student_no,
        }

    async def _classify_question(self, question: str) -> str:
        """임베딩 유사도로 질문 유형 분류 (personal / document / both)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _graduation_classifier.classify, question)

    # =============================================
    # 경로 1: 개인 현황 (DB)
    # =============================================

    async def _answer_from_db(self, question: str, student_id: int, db: AsyncSession) -> str:
        report = await self._check_graduation_status(db, student_id)
        if "error" in report:
            return report["error"]
        context = self._build_db_context(report)
        prompt = self._build_db_prompt(question, context)
        return await llm_service.answer(prompt, max_tokens=1024)

    # =============================================
    # 경로 2: 공식 문서 (RAG)
    # =============================================

    async def _answer_from_rag(self, question: str, cohort_year: int | None = None) -> tuple[str, dict]:
        """규정 문서 조회 답변.

        cohort_year: 이 답변의 '기준 학번'. 입학연도별로 값이 갈리는 규정(수료기준 등)에서
        어느 구간을 골라야 하는지 LLM에 알려준다. 학과 없는 계정처럼 기준이 없으면 None.
        """
        import time
        t1 = time.time()
        # 입학연도별로 갈리는 규정은 검색어에도 학번을 붙여야 그 코호트 표가 딸려온다.
        # 프롬프트 지시만으로는 부족했다 — 근거 자체가 안 실려 LLM이 최신 표(2026학년도 입학자
        # 기준)를 질문자 학번 것인 양 답했다(실측: 2024학번에게 30/32학점. 실제는 34~67학점).
        # 실측: '1학년 수료 기준 학점' → 34/67 미포함 / '… 2024학번' → 포함.
        search_q = question
        if cohort_year and _COHORT_SENSITIVE_RE.search(question or ""):
            search_q = f"{question} {cohort_year}학번"
            print(f"[Graduation] 코호트 민감 질문 → 검색어에 학번 부착: '{search_q}'")
        rag_context, metadata = await self._search_rag(search_q)
        print(f"[Graduation] RAG 검색 완료: {time.time()-t1:.1f}초")

        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer
        from pathlib import Path
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get("graduation", [])
        )

        # 수료 질문이면 규정 문서로 범위를 좁혀 '수료기준'만으로 한 번 더 검색해, 구간별 표를
        # 모두 컨텍스트 앞에 확보한다. 어느 구간을 고를지는 GRADUATION_COHORT_DIRECTIVE가 판단.
        if cohort_year and _COMPLETION_RE.search(question or ""):
            try:
                extra = await loop.run_in_executor(
                    None, lambda: rag_service.retriever.search(
                        question="수료기준", source=_COMPLETION_SRC,
                        topic="graduation", original_question="수료기준")
                )
                if extra:
                    add = "\n\n".join(r.text for r in extra)
                    rag_context = f"[수료기준 관련 조문]\n{add}\n\n{rag_context or ''}"[:3200]
                    metadata["rag_empty"] = False
                    print(f"[Graduation] 수료기준 보조검색 → +{len(extra)}청크")
            except Exception as e:
                print(f"[Graduation] 수료기준 보조검색 실패(무시): {e}")

        # 검색 0건이면 LLM을 호출하지 않는다. "못 찾음" 문자열을 컨텍스트로 받은 LLM이 근거 없이
        # 절차·수치를 창작하기 때문(rag_general의 동일 가드를 여기에도 세운다).
        if metadata.get("rag_empty"):
            print("[Graduation] ⚠️ RAG 0건 → LLM 스킵(환각 방지)")
            if files:
                metadata["files_to_offer"] = [Path(f).stem for f in files]
                stems = "\n".join(f"- {Path(f).stem}" for f in files)
                return (
                    "질문하신 내용은 코파일럿이 정리해 둔 자료에는 없지만, 관련 안내 파일이 준비되어 있어요.\n\n"
                    f"{stems}\n\n파일 드릴까요?",
                    metadata,
                )
            # 최후 보류: 졸업 문서로 못 잡았지만 FAQ감(과잠·엠티 등)이 임베딩상 graduation으로
            # 오라우팅됐을 수 있다 → 큐레이션 FAQ를 한 번 더 조회한다(general/rag_general과 동일).
            from app.services.faq_index import faq_lookup
            hit = await loop.run_in_executor(None, faq_lookup, question)
            if hit:
                print("[Graduation] 졸업 문서 0건이지만 FAQ 매칭 → verbatim 답변")
                metadata["source"] = "faq"
                for k in ("url", "contact_name", "contact_phone", "source_file"):
                    metadata.pop(k, None)
                return hit[0], metadata
            return (
                "죄송해요, 졸업 관련 해당 내용의 공식 자료를 찾지 못했어요. "
                "조금 더 구체적으로 질문해 주시거나 학과 사무실에 문의해 주세요.",
                metadata,
            )

        # 근거가 약한데 검수 FAQ가 있으면 LLM을 아예 안 태운다(rag_general과 같은 처방).
        # 위 '0건' FAQ 폴백은 검색이 통째로 실패했을 때만 걸려서, 어휘 매칭으로 무관 문서가
        # 살아난 경우는 빠져나간다. 실측: '재수강 최대 학점 몇이야?'가 졸업규정을 잡고
        # "재수강 최대 학점은 없습니다"로 단정했다(FAQ엔 6학점·2회·A+가 있는데도).
        # (제거됨) 근거가 약할 때 FAQ로 갈아타던 경로 — rag_general과 같은 이유로 뺀다.
        # FAQ가 중간에서 낚아채면 검색이 잡은 진짜 근거가 버려진다. 근거 약함은 '검색 실패'가
        # 아니므로, 아래 WEAK_EVIDENCE_DIRECTIVE(단정 금지)를 붙여 LLM이 답하게 둔다.
        # FAQ는 위 '졸업 문서 0건' 경로에만 남긴다.

        prompt = self._build_rag_prompt(question, rag_context)
        # 입학연도별로 값이 갈리는 규정은 '누구 기준인지'를 고정해준다(수료기준·편입생 학점 등).
        if cohort_year:
            prompt = GRADUATION_COHORT_DIRECTIVE.format(year=cohort_year) + prompt
        # 리랭커 0점 → 어휘 매칭으로만 살아난 컨텍스트면 '단정 금지' 지시를 앞에 붙인다.
        if metadata.get("weak_evidence"):
            print("[Graduation] ⚠️ 근거 약함(어휘 매칭 구제) → 단정 금지 지시 주입")
            prompt = WEAK_EVIDENCE_DIRECTIVE + prompt
        t2 = time.time()
        result = await llm_service.answer(prompt)
        print(f"[Graduation] LLM 추론 완료: {time.time()-t2:.1f}초")

        # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정. LLM 태그는 화면에서 제거만.
        result = clean_answer(result)
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    # =============================================
    # 경로 3: 개인 현황 + 공식 문서 (DB + RAG)
    # =============================================

    async def _answer_from_db_and_rag(self, question: str, student_id: int, db: AsyncSession) -> tuple[str, dict]:
        report, rag_data = await asyncio.gather(
            self._check_graduation_status(db, student_id),
            self._search_rag(question),
        )
        rag_context, metadata = rag_data
        db_context = report.get("error") if "error" in report else self._build_db_context(report)

        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer
        from pathlib import Path
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get("graduation", [])
        )

        prompt = self._build_combined_prompt(question, db_context, rag_context)
        # 구조적 졸업 답변은 실행마다 흔들리면 안 되므로 결정론적으로(temp 0.0) 생성.
        # (0.3에서 '학점 기준' 섹션이 통째로 누락되는 변덕이 관측됨)
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)

        # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정. LLM 태그는 화면에서 제거만.
        result = clean_answer(result)
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def _search_rag(self, question: str) -> tuple[str, dict]:
        """RAG 검색 (별도 스레드 실행 - LLM과 충돌 방지)"""
        loop = asyncio.get_event_loop()
        context, results = await loop.run_in_executor(
            None,
            lambda: rag_service.search_context_with_results(
                question, topic="graduation", original_question=question
            ),
        )
        if context:
            # 컨텍스트를 과도하게(500자) 자르면 얇은 근거로 LLM이 빈자리를 창작(fabrication)한다.
            # (예: "호텔경영학과 졸업요건" → 없는 학점·TOEIC 숫자 지어냄)
            # 리트리버가 이미 MAX_CHUNKS/MAX_MERGED_LENGTH/MAX_TOTAL_CONTEXT(3200)로 상한을
            # 두므로 여기서 또 조일 이유가 적다. 2000자였을 때는 리트리버가 넘겨준 컨텍스트의
            # 뒤쪽이 잘려나갔다(실측: 간호학과 875자·외식조리 848자 폐기). 학과 문서는 최상위로
            # 정렬돼 앞쪽에 오므로 학과 요건 자체가 유실되진 않았지만, 프롬프트가 요구하는
            # '세부 졸업요건 빠짐없이 나열'의 근거(졸업사정 세부지침 등)가 깎여 나갔다.
            # → 리트리버 상한과 맞춰 3000자로 올린다.
            return context[:3000], rag_service.primary_metadata(results, topic="graduation")
        # 검색 0건. 호출부가 LLM 호출을 건너뛰도록 rag_empty 플래그를 남긴다 — 이 신호가 없으면
        # "관련 공식 문서를 찾지 못했습니다."가 컨텍스트로 LLM에 들어가 빈칸을 창작한다
        # (실측: '조기졸업' 답변에 근거 없는 '학부모와 상담' 등장, src=None).
        return (
            "관련 공식 문서를 찾지 못했습니다.",
            {"source": None, "source_file": None, "topic": "graduation", "rag_empty": True},
        )

    # =============================================
    # DB 조회
    # =============================================

    async def _get_student(self, db: AsyncSession, student_id: int):
        """학생 정보 + 학과명 조회"""
        result = await db.execute(
            select(Student, Department.name)
            .join(Department, Student.dept_id == Department.id)
            .where(Student.id == student_id)
        )
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]  # (Student, dept_name)

    async def _get_requirement_rule(self, db: AsyncSession, dept_id: int, admission_year: int):
        """졸업요건 규칙 조회"""
        set_result = await db.execute(
            select(RequirementSet).where(
                RequirementSet.dept_id == dept_id,
                RequirementSet.admission_year == admission_year
            )
        )
        req_set = set_result.scalar_one_or_none()
        if not req_set:
            return None, None

        rule_result = await db.execute(
            select(RequirementRule).where(RequirementRule.set_id == req_set.id)
        )
        return req_set, rule_result.scalar_one_or_none()

    async def _resolve_requirement_rule(self, db: AsyncSession, dept_id: int, requested_year: int):
        """요청 연도로 요건을 찾되, 없으면 그 학과에서 '가장 가까운' 연도로 폴백한다.

        반환 (rule, actual_year, is_fallback):
          - rule: 사용할 RequirementRule (학과에 등록된 요건이 아예 없으면 None)
          - actual_year: 실제로 사용한 연도 (폴백이면 대체 연도)
          - is_fallback: 요청 연도가 없어 다른 연도로 대체했는지

        '가장 가까운 연도' = 요청 연도 이하 중 최신(가장 가까운 과거 코호트).
        요청 연도가 등록된 모든 연도보다 이르면 가장 오래된 연도를 쓴다.
        (예: 2028 요청 + DB에 2022~2025 등록 → 2025 / 2019 요청 → 2022)
        즉 '2028학번 요건 없음' 같은 경우 조용히 아무거나 주는 대신, 가장 최근 요건으로
        폴백하고 호출부가 그 사실을 답변에 자연스럽게 밝히도록 is_fallback을 돌려준다.
        """
        # 1) 정확일치 우선
        _set, rule = await self._get_requirement_rule(db, dept_id, requested_year)
        if rule:
            return rule, requested_year, False

        # 2) 그 학과에 등록된 연도 전부 조회
        years = (await db.execute(
            select(RequirementSet.admission_year).where(RequirementSet.dept_id == dept_id)
        )).scalars().all()
        years = sorted({int(y) for y in years if y is not None})
        if not years:
            return None, requested_year, False   # 학과 자체에 요건 없음 → 기존 환각방지 스킵이 처리

        # 3) 가장 가까운 연도 선택 후 그 규칙 조회
        le = [y for y in years if y <= requested_year]
        actual_year = le[-1] if le else years[0]
        _set2, rule2 = await self._get_requirement_rule(db, dept_id, actual_year)
        if rule2:
            return rule2, actual_year, True
        return None, requested_year, False       # 대체 연도에도 유효 규칙 없음 → 폴백 취급 안 함

    async def _latest_year(self, db: AsyncSession, dept_id: int) -> int | None:
        """그 학과에 등록된 가장 최근 입학연도(요건 기준 연도). 없으면 None.
        연도를 명시 안 한 학과 요건 질문의 기본값으로 쓴다(최신 코호트 기준)."""
        return (await db.execute(
            select(func.max(RequirementSet.admission_year)).where(RequirementSet.dept_id == dept_id)
        )).scalar_one_or_none()

    async def _get_earned_credits(self, db: AsyncSession, student_id: int) -> dict:
        """이수 학점 카테고리별 합산

        재수강 대응: student_course에 (student_id, course_code) 유니크 제약이 없어
        같은 과목이 여러 행일 수 있으므로, 통과한 과목 코드를 중복 제거(distinct)한 뒤
        과목당 학점을 한 번만 합산한다. (재수강 과목 학점 이중 계산 방지)
        """
        # 학생이 통과한 과목 코드 목록 (중복 제거)
        passed_codes = (
            select(distinct(StudentCourse.course_code))
            .where(
                StudentCourse.student_id == student_id,
                StudentCourse.is_passed == True,
            )
            .scalar_subquery()
        )
        result = await db.execute(
            select(Course.category, func.sum(Course.credits))
            .where(Course.code.in_(passed_codes))
            .group_by(Course.category)
        )
        return {row[0]: float(row[1]) for row in result.all()}

    async def _has_english_cert(self, db: AsyncSession, student_id: int) -> bool:
        """영어 공인성적 보유 여부 확인"""
        result = await db.execute(
            select(StudentAchievement).where(
                StudentAchievement.student_id == student_id
            )
        )
        achievements = result.scalars().all()
        return any(a.type == "english_cert" and a.value == "PASS" for a in achievements)

    # =============================================
    # 졸업 여부 계산
    # =============================================

    async def _check_graduation_status(self, db: AsyncSession, student_id: int) -> dict:
        """졸업 요건 충족 여부 종합 계산"""
        is_graduated = True
        insufficient_details = []

        # 학생 조회
        student, dept_name = await self._get_student(db, student_id)
        if not student:
            return {"error": "등록된 학생을 찾을 수 없습니다."}

        # 입학연도 추출
        try:
            admission_year = int(student.student_no[:4])
        except (ValueError, TypeError, IndexError):
            admission_year = 2026
            print(f"[Warning] 입학연도 추출 실패, 2026으로 설정 (학번: {student.student_no})")

        # 졸업요건 조회
        req_set, rule = await self._get_requirement_rule(db, student.dept_id, admission_year)
        if not req_set:
            return {"error": f"{dept_name}({admission_year}년도 입학) 졸업요건 정보가 등록되어 있지 않습니다."}
        if not rule:
            return {"error": "졸업요건 세부 규칙이 설정되어 있지 않습니다."}

        # 이수 학점 계산 (DB category 값: "전공필수", "교양필수")
        passed_credits = await self._get_earned_credits(db, student_id)
        earned_major   = (passed_credits.get("전공필수", 0.0) + passed_credits.get("전공선택", 0.0))
        earned_liberal = (passed_credits.get("교양필수", 0.0) + passed_credits.get("교양선택", 0.0))
        earned_general = passed_credits.get("일반", 0.0)

        # 트랙(다전공): 전공·교양과 나란한 '독립 이수구분'. category "트랙" 집계로 계산.
        # req_track이 None인 학과는 트랙 요건 없음(트랙 과목 없으면 earned_track=0).
        req_track    = rule.min_credits_track
        earned_track = passed_credits.get("트랙", 0.0)

        # 총 이수학점 = 전공+교양+일반+트랙 (모든 이수구분 학점 합산 — 트랙도 포함해야 증발 안 함)
        total_earned = earned_major + earned_liberal + earned_general + earned_track

        # 학점 충족 여부 확인
        if earned_major < rule.min_credits_major:
            is_graduated = False
            insufficient_details.append(f"전공 {rule.min_credits_major - earned_major}학점 부족")

        if earned_liberal < rule.min_credits_liberal:
            is_graduated = False
            insufficient_details.append(f"교양 {rule.min_credits_liberal - earned_liberal}학점 부족")

        if earned_general < rule.min_credits_general:
            is_graduated = False
            insufficient_details.append(f"일반 {rule.min_credits_general - earned_general}학점 부족")

        if total_earned < rule.min_credits_total:
            is_graduated = False
            insufficient_details.append(f"총학점 {rule.min_credits_total - total_earned}학점 부족")

        # 트랙 부족 판정 — 트랙 요건이 있는 학과만
        if req_track is not None and earned_track < req_track:
            is_graduated = False
            insufficient_details.append(f"트랙 {req_track - earned_track}학점 부족")

        # 영어 인증 확인
        english_cert_passed = await self._has_english_cert(db, student_id)
        if not english_cert_passed:
            is_graduated = False
            insufficient_details.append("영어 공인성적 미취득")

        return {
            "is_graduated":       is_graduated,
            "english_cert_passed": english_cert_passed,
            "dept_name":          dept_name,
            "earned_major":       earned_major,
            "req_major":          rule.min_credits_major,
            "earned_liberal":     earned_liberal,
            "req_liberal":        rule.min_credits_liberal,
            "earned_general":     earned_general,
            "req_general":        rule.min_credits_general,
            "earned_track":       earned_track,
            "req_track":          req_track,
            "total_earned":       total_earned,
            "total_required":     rule.min_credits_total,
            "insufficient_details": insufficient_details,
        }

    # =============================================
    # LLM 프롬프트 생성
    # =============================================

    def _build_db_context(self, report: dict) -> str:
        """DB 조회 결과를 LLM 컨텍스트 문자열로 변환"""
        status = "졸업 가능" if report["is_graduated"] else "졸업 불가"

        # 초과 이수 시 음수가 나오지 않도록 0으로 클램프
        major_short   = max(0, report['req_major'] - report['earned_major'])
        liberal_short = max(0, report['req_liberal'] - report['earned_liberal'])
        general_short = max(0, report['req_general'] - report['earned_general'])
        total_short   = max(0, report['total_required'] - report['total_earned'])

        dept_name = report.get("dept_name", "")
        english_status = "취득 완료" if report.get("english_cert_passed") else "미취득"

        # 트랙(다전공): 요건이 있는 학과만 표시
        track_line = ""
        if report.get("req_track") is not None:
            track_short = max(0, report["req_track"] - report["earned_track"])
            track_line = (
                f"트랙 학점: 현재 {report['earned_track']}학점 이수, "
                f"졸업에 필요한 학점 {report['req_track']}학점, 아직 부족한 학점 {track_short}학점\n"
            )

        return (
            f"[학생 졸업요건 조회 결과 - 아래 수치는 정확한 DB 데이터임]\n"
            f"학과: {dept_name}\n"
            f"졸업 가능 여부: {status}\n\n"
            f"전공 학점: 현재 {report['earned_major']}학점 이수, 졸업에 필요한 학점 {report['req_major']}학점, 아직 부족한 학점 {major_short}학점\n"
            f"교양 학점: 현재 {report['earned_liberal']}학점 이수, 졸업에 필요한 학점 {report['req_liberal']}학점, 아직 부족한 학점 {liberal_short}학점\n"
            f"일반 학점: 현재 {report['earned_general']}학점 이수, 졸업에 필요한 학점 {report['req_general']}학점, 아직 부족한 학점 {general_short}학점\n"
            f"{track_line}"
            f"총 이수 학점: 현재 {report['total_earned']}학점 이수, 졸업에 필요한 총 학점 {report['total_required']}학점, 아직 부족한 학점 {total_short}학점\n"
            f"영어 공인성적: {english_status}\n"
        )

    def _build_db_prompt(self, question: str, context: str) -> str:
        return GRADUATION_DB_PROMPT.format(context=context, question=question)

    def _build_rag_prompt(self, question: str, rag_context: str) -> str:
        return GRADUATION_RAG_PROMPT.format(rag_context=rag_context, question=question)

    def _build_combined_prompt(self, question: str, db_context: str, rag_context: str) -> str:
        return GRADUATION_COMBINED_PROMPT.format(db_context=db_context, rag_context=rag_context, question=question)


# 싱글톤 인스턴스
graduation_service = GraduationService()
