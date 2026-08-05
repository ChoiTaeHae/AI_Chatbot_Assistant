"""
학식 주간 식단 조회 서비스

meal_list.jsp에서 5개 식당(학생식당 서캠/동캠, 국제기숙사, 청운숙기숙사, 기숙사 동캠)의
주간 식단을 크롤링해 in-memory 캐시로 보관한다. DB 테이블을 쓰지 않는 이유:
데이터가 작고(수백 행) 매주 갱신되는 휘발성 데이터라, 학교 원본 사이트가 항상 최신 출처이므로
재시작 시 캐시가 비어도 다음 조회에서 즉시(약 0.2초) 재크롤되어 무해하다.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup, Tag

MEAL_LIST_URL = "https://www.wsu.ac.kr/page/meal_list.jsp"
# 식당 안내(위치·전화·운영시간·가격) 출처. 학교에는 같은 자리(HOME > 대학생활 > 복지시설안내 >
# 학생식당)에 표가 두 벌 있는데, 홈페이지 메뉴가 실제로 링크하는 쪽은 campus0806이다
# (scampus0806은 어디서도 링크되지 않는 고아 페이지 — 2026-07-29 확인).
# 옛 페이지에는 교직원식당 가격이 아예 없고 메뉴별 가격도 현행과 달라 신뢰할 수 없어 교체했다.
#   교체로 얻는 것: 교직원식당 5,000원 / 푸드코트 가격, 기숙사 '미운영' 명시
#   교체로 잃는 것: 어학센터 식당 항목, 학생식당 백반·라면정식 가격
GUIDE_URL = "https://www.wsu.ac.kr/page/index.jsp?code=campus0806"
REQUEST_TIMEOUT_SECONDS = 15

# 데이터가 없어 코드로는 답을 만들 수 없는 질문(주말 식단, 방학 중 미운영, 안내표에서 빠진
# 식당)에 붙이는 안내. "정보가 없어요"로 끝내면 사용자가 갈 곳이 없으므로 원본을 가리킨다.
# 좌측 '학생식당' 탭은 같은 주간 캐시를 쓰면서 식당·요일을 직접 고를 수 있어(Sidebar.jsx),
# 대화로 한 번에 못 짚는 날짜·식당 조합은 오히려 그쪽이 빠르다.
# 링크는 meal_list.jsp(크롤용 원본 표)가 아니라 campus0806을 준다 — 전자는 사이트 껍데기
# 없이 표만 뜨는 페이지라 사용자가 열어도 길을 잃는다. 식단 자체는 좌측 탭이 더 빠르다.
_MENU_SOURCE_NOTE = (
    "좌측 '학생식당' 탭에서 식당과 요일을 골라 이번 주 식단을 볼 수 있어요.\n"
    f"[우송대 식당 안내 바로가기]({GUIDE_URL})"
)
_GUIDE_SOURCE_NOTE = f"[식당 위치·운영시간·가격 안내 바로가기]({GUIDE_URL})"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# caption "OO의 날짜별 메뉴를 제공하는 표"에서 식당명만 추출
_CAPTION_NAME_RE = re.compile(r"^(.+?)의\s*날짜별")


@dataclass
class RestaurantMenu:
    name: str
    columns: list[str]                          # 코너/식사 구분 (예: ["조식","중식","석식"])
    days: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # days: {"07.06": {"중식": ["계란라면", "쌀밥", ...], ...}, ...}


@dataclass
class RestaurantGuide:
    name: str
    location: str | None = None
    phone: str | None = None
    hours: str | None = None
    price: str | None = None


def _fetch(url: str) -> str:
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content.decode("utf-8", errors="replace")


def _fetch_meal_html() -> str:
    return _fetch(MEAL_LIST_URL)


def _fetch_guide_html() -> str:
    return _fetch(GUIDE_URL)


# 안내 표 행 라벨(startswith 매칭, "운영시간 (토,일,공휴일 휴무)"처럼 라벨에 부가설명이
# 붙는 경우 대응) → RestaurantGuide 속성명
_GUIDE_FIELD_MAP = {
    "위치": "location",
    "전화번호": "phone",
    "운영시간": "hours",
    "메뉴별 가격": "price",
}


def _parse_guide_html(html: str) -> dict[str, RestaurantGuide]:
    """식당안내 표(속성=행, 식당=열인 pivot 구조) 파싱.

    가격 행처럼 colspan으로 여러 식당에 값 하나가 걸쳐 있는 셀이 있어(예: 서캠+동캠
    가격이 같은 셀 하나), 단순 zip이 아니라 colspan만큼 값을 펼쳐서 배정해야 한다.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return {}

    rows = table.find_all("tr")
    if not rows:
        return {}

    header_cells = rows[0].find_all(["th", "td"])
    restaurant_names = [c.get_text(" ", strip=True) for c in header_cells[1:]]
    guides = {name: RestaurantGuide(name=name) for name in restaurant_names}

    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        label = cells[0].get_text(" ", strip=True)
        field = next((attr for prefix, attr in _GUIDE_FIELD_MAP.items() if label.startswith(prefix)), None)
        if not field:
            continue

        col_idx = 0
        for cell in cells[1:]:
            span = int(cell.get("colspan") or 1)
            value = cell.get_text(" ", strip=True)
            if value and value != "-":
                for offset in range(span):
                    if col_idx + offset < len(restaurant_names):
                        setattr(guides[restaurant_names[col_idx + offset]], field, value)
            col_idx += span

    return guides


def _extract_restaurant_name(table: Tag) -> str | None:
    caption = table.find("caption")
    if not caption:
        return None
    text = caption.get_text(" ", strip=True)
    m = _CAPTION_NAME_RE.match(text)
    return m.group(1).strip() if m else text.strip() or None


def _parse_meal_html(html: str) -> dict[str, RestaurantMenu]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, RestaurantMenu] = {}

    for table in soup.find_all("table", class_="tbl_skin2"):
        name = _extract_restaurant_name(table)
        if not name:
            continue

        thead = table.find("thead")
        header_cells = thead.find_all("th") if thead else []
        # 첫 컬럼은 "날짜" 헤더이므로 제외하고 코너/식사 구분명만 남긴다
        columns = [th.get_text(" ", strip=True) for th in header_cells[1:]]

        tbody = table.find("tbody") or table
        days: dict[str, dict[str, list[str]]] = {}
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            date_str = cells[0].get_text(" ", strip=True)
            if not date_str:
                continue

            row: dict[str, list[str]] = {}
            for col_name, cell in zip(columns, cells[1:]):
                items = [s for s in cell.stripped_strings]
                if items:
                    row[col_name] = items
            if row:
                days[date_str] = row

        result[name] = RestaurantMenu(name=name, columns=columns, days=days)

    return result


def _iso_week_key(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


# ── in-memory 캐시 (lazy) ────────────────────────────────────────────
_cache: dict[str, RestaurantMenu] | None = None
_cache_week: str | None = None


def get_menu_data(force: bool = False) -> dict[str, RestaurantMenu]:
    """이번 주 캐시가 있으면 그대로 반환, 없으면(주가 바뀌었거나 최초 호출) 재크롤."""
    global _cache, _cache_week

    current_week = _iso_week_key(date.today())
    if force or _cache is None or _cache_week != current_week:
        html = _fetch_meal_html()
        _cache = _parse_meal_html(html)
        _cache_week = current_week
        total_days = sum(len(m.days) for m in _cache.values())
        print(f"[Dining] 메뉴 갱신 완료 (주차={current_week}, 식당={len(_cache)}개, 총 {total_days}일치)")

    return _cache


# 위치/시간/가격/전화는 메뉴처럼 주 단위로 바뀌지 않는 정적 정보지만, 별도 만료
# 정책을 두지 않고 메뉴와 동일하게 주 단위로 재크롤한다 — 정책을 하나로 단순화.
_guide_cache: dict[str, RestaurantGuide] | None = None
_guide_cache_week: str | None = None


def get_guide_data(force: bool = False) -> dict[str, RestaurantGuide]:
    global _guide_cache, _guide_cache_week

    current_week = _iso_week_key(date.today())
    if force or _guide_cache is None or _guide_cache_week != current_week:
        html = _fetch_guide_html()
        _guide_cache = _parse_guide_html(html)
        _guide_cache_week = current_week
        print(f"[Dining] 안내정보 갱신 완료 (주차={current_week}, 식당={len(_guide_cache)}개)")

    return _guide_cache


# ── 질의 해석 (날짜/식당) ─────────────────────────────────────────────

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]  # date.weekday() 인덱스 순서
_WEEKDAY_RE = re.compile(r"(월|화|수|목|금|토|일)요일")


def _resolve_date_key(question: str) -> str:
    """질문에서 날짜 의도를 파싱해 캐시 키 형식("MM.DD")으로 변환. 명시 없으면 오늘."""
    today = date.today()

    if "모레" in question:
        return (today + timedelta(days=2)).strftime("%m.%d")
    if "내일" in question:
        return (today + timedelta(days=1)).strftime("%m.%d")

    m = _WEEKDAY_RE.search(question)
    if m:
        target_idx = _WEEKDAY_KO.index(m.group(1))
        monday = today - timedelta(days=today.weekday())
        return (monday + timedelta(days=target_idx)).strftime("%m.%d")

    # "오늘" 명시든 날짜 언급이 아예 없든 기본값은 오늘
    return today.strftime("%m.%d")


# 사용자 발화 표현 → 캐시에 저장된 정확한 식당명. 기숙사 3곳은 실측상 메뉴가 동일해
# (같은 위탁업체) "기숙사"만 언급되면 국제기숙사를 대표로 사용한다.
_RESTAURANT_ALIASES: dict[str, str] = {
    "서캠퍼스학생식당": "학생식당(서캠)",
    "서캠퍼스": "학생식당(서캠)",
    "서캠": "학생식당(서캠)",
    "동캠퍼스학생식당": "학생식당(동캠)",
    "동캠퍼스": "학생식당(동캠)",
    "동캠": "학생식당(동캠)",
    "국제기숙사": "국제기숙사",
    "청운숙기숙사": "청운숙기숙사",
    "청운숙": "청운숙기숙사",
    "기숙사동캠": "기숙사(동캠)",
    "기숙사": "국제기숙사",
    # '학생식당'만 말하면 서캠. 이 별칭이 없어서 "학생식당 아침 뭐야"가 '식당명 없음'으로
    # 판정돼 직전 질문(기숙사)을 물려받아 기숙사 조식을 답하던 버그가 있었다(실측).
    "학생식당": "학생식당(서캠)",
}
# 별칭은 '긴 것부터' 본다. 삽입 순서대로 훑으면 짧은 별칭이 더 구체적인 이름을 가로챈다 —
# 실측: '동캠기숙사 뭐야'가 '동캠'에 먼저 걸려 학생식당(동캠) 메뉴를 답했다.
# ('동캠기숙사'는 '기숙사'로 매칭돼 국제기숙사가 되는데, 세 기숙사는 메뉴가 같아
#  '기숙사(국제·청운숙·동캠 공통)' 라벨로 나가므로 답으로도 맞다)
_ALIAS_ORDER = sorted(_RESTAURANT_ALIASES, key=len, reverse=True)
_DEFAULT_RESTAURANT = "학생식당(서캠)"

# 끼니 키워드 → 컬럼명. 기숙사(조식/중식/석식)에만 매칭되고, 학생식당 코너명
# (소담상/한식 등)엔 자연히 안 걸려 전체 표시가 유지된다.
#
# '천원의아침밥'은 식당이 아니라 학생식당 표의 코너(컬럼)다 — 서캠·동캠 둘 다 갖고 있다.
# 별칭 사전(_RESTAURANT_ALIASES)에 없어서 '천원의 아침밥 뭐 나와'가 식당명 없음으로 판정되고,
# '아침'이 조식으로 매핑되는데 학생식당엔 조식 컬럼이 없어 그냥 전체 표시가 됐다(실측:
# 교직원 코너만 나옴). 컬럼명을 직접 가리키도록 맨 앞에 둔다 — '아침'보다 먼저 매칭돼야
# 하고, 사용자가 띄어쓰기를 어떻게 하든 걸리도록 표기를 나눠 적는다.
_MEAL_ALIASES: dict[str, str] = {
    "천원의아침밥": "천원의아침밥", "천원의 아침밥": "천원의아침밥",
    "천원아침밥": "천원의아침밥", "천원 아침밥": "천원의아침밥",
    "천원의아침": "천원의아침밥", "천원의 아침": "천원의아침밥",
    "아침": "조식", "조식": "조식", "모닝": "조식",
    "점심": "중식", "중식": "중식", "런치": "중식",
    "저녁": "석식", "석식": "석식", "디너": "석식",
}


def _resolve_meal(question: str, columns: list[str]) -> str | None:
    """질문에 끼니 키워드가 있고 해당 컬럼이 존재하면 그 컬럼명 반환, 아니면 None(전체 표시)."""
    for alias, col in _MEAL_ALIASES.items():
        if alias in question and col in columns:
            return col
    return None


def _resolve_restaurant(question: str, available: dict[str, RestaurantMenu]) -> tuple[str, bool]:
    """(식당명, 사용자가 명시했는가) 반환. 명시 없으면 기본값(서캠 학생식당) + False."""
    compact = question.replace(" ", "")
    for alias in _ALIAS_ORDER:
        real_name = _RESTAURANT_ALIASES[alias]
        if alias in compact and real_name in available:
            return real_name, True

    default = _DEFAULT_RESTAURANT if _DEFAULT_RESTAURANT in available else next(iter(available), "")
    return default, False


# ── 질의 해석 (위치/시간/가격/전화) ────────────────────────────────────
# 주간 식단 표(5개: 서캠/동캠/국제기숙사/청운숙기숙사/기숙사동캠)와 안내 표(4개: 서캠/동캠/
# 어학센터/기숙사)는 식당 구분 단위가 달라 이름이 서로 다르다. 안내 표는 기숙사 3곳을
# "기숙사 식당" 하나로 뭉뚱그리므로, 메뉴 쪽 3개 기숙사 이름을 전부 그 하나로 매핑한다.
_MENU_TO_GUIDE_NAME: dict[str, str] = {
    "학생식당(서캠)": "서캠퍼스 학생식당",
    "학생식당(동캠)": "동캠퍼스 학생식당",
    "국제기숙사": "기숙사 식당",
    "청운숙기숙사": "기숙사 식당",
    "기숙사(동캠)": "기숙사 식당",
}
# 어학센터 식당은 주간 식단이 없어(_RESTAURANT_ALIASES에 없음) 안내 정보 전용으로만 취급
_GUIDE_ONLY_ALIASES: dict[str, str] = {
    "어학센터": "어학센터 식당",
    "어학센터식당": "어학센터 식당",
}
_DEFAULT_GUIDE_NAME = "서캠퍼스 학생식당"


def _resolve_guide_name(question: str) -> tuple[str, bool]:
    """(안내표 식당명, 사용자가 명시했는가) 반환."""
    compact = question.replace(" ", "")
    for alias, guide_name in _GUIDE_ONLY_ALIASES.items():
        if alias in compact:
            return guide_name, True
    for alias in _ALIAS_ORDER:                    # 메뉴 쪽과 같은 '긴 별칭 우선' 규칙
        if alias in compact:
            menu_name = _RESTAURANT_ALIASES[alias]
            return _MENU_TO_GUIDE_NAME.get(menu_name, menu_name), True
    return _DEFAULT_GUIDE_NAME, False


_LOCATION_KW = ("위치", "어디")
_PHONE_KW = ("전화", "연락처", "번호")
_PRICE_KW = ("가격", "얼마", "값", "요금")
_HOURS_KW = ("몇시", "몇 시", "운영시간", "영업시간", "언제까지", "언제부터", "몇시까지", "몇시부터")


def _resolve_intent(question: str) -> str:
    """질문 의도를 menu/location/phone/price/hours 중 하나로 분류. 기본값은 menu."""
    if any(kw in question for kw in _LOCATION_KW):
        return "location"
    if any(kw in question for kw in _PHONE_KW):
        return "phone"
    if any(kw in question for kw in _PRICE_KW):
        return "price"
    if any(kw in question for kw in _HOURS_KW):
        return "hours"
    return "menu"


_GUIDE_FIELD_LABEL = {"location": "위치", "phone": "전화번호", "price": "가격", "hours": "운영시간"}

# 학교 안내표의 '서캠퍼스 학생식당' 열은 위치를 '학생회관 2층'으로만 적어 두었는데, 2층은 실제로
# 교직원식당·푸드코트다(같은 열의 운영시간·가격 셀이 그렇게 적혀 있다). 학생식당은 1층에 따로
# 있고, 기간에 따라 두 곳을 한 층에서 통합운영하며 그때그때 복지팀 공지로 고지된다.
# 한 층만 답하면 학기 중 학생이 2층으로 헛걸음하므로, 위치 답변에서만 두 층을 함께 제시한다.
# (동캠은 테크노디자인센터 지하로 층 구분이 없어 대상에서 제외)
#
# expect: 학교가 표를 고쳤는지 판별하는 표식. 크롤 값에 이 문자열이 없으면 우리가 아는 상태가
#   아니라는 뜻이므로 덮어쓰기를 멈추고 원문을 그대로 보여준다 — 오래된 하드코딩이 새 정보를
#   조용히 가리는 것을 막기 위함.
# 건물코드 W16은 building 테이블의 '학생회관(서캠)' 별칭이자 다른 문서(서점·우편취급국·
# 복학지원센터 등)가 모두 쓰는 표기라 그대로 맞춘다 — 캠퍼스 지도에서 찾기 쉬워진다.
_LOCATION_OVERRIDE = {
    "서캠퍼스 학생식당": {
        "expect": "학생회관",
        "text": "서캠퍼스 학생회관(W16) — 1층 학생식당 / 2층 교직원식당·푸드코트",
    },
}
_FLOOR_NOTE = "※ 기간에 따라 한 층에서 통합운영하기도 해요. 학기 중 학생 식사는 보통 1층이에요."


def _format_guide_answer(
    guide_name: str, guide: RestaurantGuide, intent: str, explicit: bool
) -> tuple[str, bool]:
    """(답변, 안내표에서 값을 찾았는가) 반환.

    found=False는 '학교 식당안내 표에 그 칸이 비어 있다'는 뜻일 뿐, 학교에 정보가 없다는
    뜻이 아니다 — 예: 기숙사 식당 가격은 이 표엔 '-'지만 기숙사비 안내 문서에 식비가 있다.
    호출부가 이 신호를 보고 RAG로 넘길 수 있게 분리해 둔다.
    """
    value = getattr(guide, intent, None)
    label = _GUIDE_FIELD_LABEL[intent]

    override = _LOCATION_OVERRIDE.get(guide_name) if intent == "location" else None
    applied = bool(override and value and override["expect"] in value)
    if applied:
        value = override["text"]

    found = bool(value)
    if not found:
        line = f"{guide_name} {label} 정보가 없어요."
    else:
        line = f"[{guide_name}] {label}: {value}"

    lines = [line]
    if applied:
        lines.append(_FLOOR_NOTE)
    if not explicit:
        lines.append("\n(다른 식당이 궁금하면 '동캠 학식', '기숙사 식당'처럼 물어봐 주세요!)")
    # 빈 칸이어도 RAG로 넘기지 않는다(항상 True).
    # 원래는 넘겼다 — '기숙사 식당 가격'이 이 표엔 없지만 기숙사비_안내 문서에 식비
    # (1일 4,000원)가 있어서였다. 그런데 그 문서는 관리비 표가 훨씬 길어, 검색이 문서를
    # 통째로 물어 오면서 LLM이 식비 대신 관리비를 답했다(실측). 엉뚱한 금액을 자신 있게
    # 말하느니 없다고 하는 편이 낫다는 판단(2026-07-30).
    return "\n".join(lines), True


# 기숙사 3곳(국제/청운숙/동캠)은 실측상 메뉴가 완전히 동일하다(같은 위탁업체). "기숙사"라고만
# 물으면 대표로 국제기숙사 데이터를 보여주는데, 라벨을 "[국제기숙사]"로만 표시하면 사용자가
# "청운숙/동캠도 같은 건가?"라고 의심할 수 있어 공통 메뉴임을 명시적으로 표시한다.
_SHARED_MENU_DORMS = {"국제기숙사", "청운숙기숙사", "기숙사(동캠)"}
_SHARED_MENU_LABEL = "기숙사(국제·청운숙·동캠 공통)"


def _display_name(restaurant: str) -> str:
    return _SHARED_MENU_LABEL if restaurant in _SHARED_MENU_DORMS else restaurant


def _guide_closed_note(restaurant: str) -> str | None:
    """학교 안내표가 그 식당을 '미운영'으로 적어 뒀으면 그 표기를 인용해 돌려준다.

    '방학이라 안 해요'라고 우리가 단정하지 않는 이유: 크롤 0일치는 미운영일 수도, 식단이
    아직 안 올라온 것일 수도 있고, 안내표엔 이유가 안 적혀 있다. 실제로 같은 주에 국제기숙사는
    7일치 식단이 있는데 안내표의 '기숙사 식당' 운영시간은 '미운영'이라 두 출처가 어긋난다.
    그래서 학교가 쓴 말을 그대로 인용만 하고, 해석은 붙이지 않는다.
    """
    try:
        guide = get_guide_data().get(_MENU_TO_GUIDE_NAME.get(restaurant, restaurant))
    except Exception as e:
        print(f"[Dining] 안내표 조회 실패(무시): {e}")
        return None
    if guide and guide.hours and "미운영" in guide.hours:
        return f"참고로 학교 식당안내에는 '{guide.name}' 운영시간이 '{guide.hours}'으로 적혀 있어요."
    return None


def _format_answer(
    restaurant: str, date_key: str, menu: RestaurantMenu,
    explicit_restaurant: bool, meal_filter: str | None,
    closed_note: str | None = None,
) -> str:
    display = _display_name(restaurant)
    try:
        month, day = date_key.split(".")
        weekday_idx = date(date.today().year, int(month), int(day)).weekday()
        date_label = f"{date_key} ({_WEEKDAY_KO[weekday_idx]})"
    except Exception:
        date_label = date_key

    day_data = menu.days.get(date_key)
    if not day_data:
        # 데이터가 없을 땐 공통 라벨('기숙사(국제·청운숙·동캠 공통)') 대신 실제 식당명을 쓴다.
        # 공통 라벨로 "정보가 없어요"라고 하면, 같은 라벨로 국제기숙사 식단이 나오는 다른
        # 질문과 모순돼 보인다(실측: 청운숙 0일치인데 국제기숙사는 7일치).
        # 여기서 국제기숙사 식단으로 대체하지는 않는다 — 0일치가 '크롤 누락'이 아니라
        # '방학 중 미운영'일 수 있어, 문 닫은 식당의 식단을 있는 것처럼 말하게 된다.
        lines = [
            f"{restaurant} {date_label} 메뉴 정보가 없어요. "
            "주말·공휴일이거나 이번 주(월~일) 범위를 벗어난 날짜일 수 있어요.",
        ]
        if closed_note:
            lines.append(closed_note)
        lines.append("\n" + _MENU_SOURCE_NOTE)
    else:
        # 끼니 필터가 있으면 해당 컬럼만, 없으면 전체 컬럼
        target_columns = [meal_filter] if meal_filter else menu.columns
        lines = [f"[{display}] {date_label} 메뉴"]
        for col in target_columns:
            items = day_data.get(col)
            if items:
                lines.append(f"- {col}: " + " / ".join(items))
        # 끼니 필터를 걸었는데 그날 그 끼니 데이터가 없는 경우
        if meal_filter and len(lines) == 1:
            lines.append(f"- {meal_filter} 메뉴 정보가 없어요.")
            lines.append("\n" + _MENU_SOURCE_NOTE)

    if not explicit_restaurant:
        lines.append("\n(다른 식당이 궁금하면 '동캠 학식', '기숙사 식단'처럼 물어봐 주세요!)")

    return "\n".join(lines)


async def _answer_menu(question: str, prev_question: str | None = None) -> str:
    try:
        data = await asyncio.to_thread(get_menu_data)
    except Exception as e:
        print(f"[Dining] 메뉴 조회 실패: {e}")
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    if not data:
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    restaurant, explicit = _resolve_restaurant(question, data)
    # 현재 질문에 식당명이 없으면("가격은?") 직전 질문에서 물려받는다. 현재 질문이 식당을
    # 명시했으면 절대 덮어쓰지 않는다 — 그래야 "동캠 학식" 뒤의 "서캠은?"이 서캠으로 간다.
    if not explicit and prev_question:
        inherited, found = _resolve_restaurant(prev_question, data)
        if found:
            print(f"[Dining] 식당명 생략 → 직전 질문에서 '{inherited}' 물려받음")
            restaurant, explicit = inherited, True
    menu = data.get(restaurant)
    if not menu:
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    date_key = _resolve_date_key(question)
    meal_filter = _resolve_meal(question, menu.columns)
    # 식단이 비어 있을 때만 안내표를 본다 — 정상 응답에 불필요한 조회를 걸지 않기 위함
    # (주 단위 캐시라 대개 즉시지만, 갱신 주가 바뀌면 크롤이 돈다)
    closed_note = (None if menu.days.get(date_key)
                   else await asyncio.to_thread(_guide_closed_note, restaurant))
    return _format_answer(restaurant, date_key, menu, explicit, meal_filter, closed_note)


async def _answer_guide(
    question: str, intent: str, prev_question: str | None = None
) -> tuple[str, bool]:
    try:
        data = await asyncio.to_thread(get_guide_data)
    except Exception as e:
        print(f"[Dining] 안내정보 조회 실패: {e}")
        # 조회 자체가 실패한 것은 '값이 없다'와 다르다. RAG로 넘겨도 답이 없으므로 found=True.
        return "학식 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.", True

    if not data:
        return "학식 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.", True

    guide_name, explicit = _resolve_guide_name(question)
    # 메뉴 쪽과 같은 원칙 — 현재 질문에 식당명이 없을 때만 직전 질문에서 물려받는다.
    if not explicit and prev_question:
        inherited, found = _resolve_guide_name(prev_question)
        if found:
            print(f"[Dining] 식당명 생략 → 직전 질문에서 '{inherited}' 물려받음")
            guide_name, explicit = inherited, True

    guide = data.get(guide_name)
    if not guide:
        # 별칭은 아는데 학교 안내표에 그 식당이 없는 경우(예: 어학센터 식당이 표에서 빠짐).
        # 조회 실패가 아니므로 '다시 시도' 안내를 주면 사용자가 계속 되물어 헛수고를 한다.
        return (
            f"'{guide_name}' 안내는 학교 식당안내 표에 올라와 있지 않아요.\n"
            f"(안내 가능한 식당: {', '.join(data)})\n\n"
            f"{_GUIDE_SOURCE_NOTE}",
            True,   # 안내 가능한 식당 목록을 준 것 자체가 답 — RAG로 넘기면 이 안내가 사라진다
        )

    return _format_guide_answer(guide_name, guide, intent, explicit)


# ── 학식 질문 확인 게이트 ──────────────────────────────────────────────
# 라우터(임베딩)는 "X 몇시까지 해" 같은 문장 구조에 강하게 반응해서, 주어가 식당이 아닌
# 질문까지 dining으로 보낸다 — 실측: '과사 점심시간 언제야?'가 서캠 학식 메뉴를 받았다.
# 임베딩 점수로는 못 가른다(실측: 학식 질문 0.629~0.848 vs 아닌 질문 0.541~0.744로 구간이
# 겹쳐, 20건 중 11건이 겹치는 구간에 들어간다. '조식 되나요' 0.741 < '도서관 몇 시까지 해'
# 0.744). 판별 신호가 '무엇을 묻는가'(운영시간)가 아니라 '누구에 대해 묻는가'(식당이냐)라
# 문장 임베딩이 약하게 보는 쪽이어서, 주체를 직접 보는 규칙으로 확인한다.
#
# 이 게이트는 라우팅 '뒤'에 놓인 거르개라 dining 답변을 줄이기만 하고 늘리지 않는다.
# 통과 못 하면 호출부가 RAG로 넘겨 큐레이션 FAQ(과사 운영시간 등)까지 닿는다.
_DINING_DOMAIN = ("학식", "식단", "급식", "식당", "메뉴", "푸드코트",
                  "조식", "중식", "석식", "천원의아침밥")
_MENU_REQUEST = ("뭐", "메뉴", "나와", "나옴", "먹")
# 날짜어와 짝지을 때는 '뭐'를 뺀다 — '오늘 뭐 해?'까지 학식으로 끌려온다.
# 끼니어·별칭처럼 학식 쪽을 가리키는 단어가 함께 있을 땐 '뭐'로 충분하다('동캠기숙사 뭐야').
_MENU_REQUEST_STRONG = ("메뉴", "나와", "나옴", "먹")
_MEAL_WORDS = ("점심", "저녁", "아침", "밥")
# '점심시간'은 끼니가 아니라 시간대를 가리킨다. 이 구분이 없으면 '과사 점심시간 뭐야?'가
# 끼니어('점심')+요청어('뭐')로 잡혀 학식 메뉴를 답한다(실측. 행정실·교무처도 같은 형태).
_MEALTIME_PHRASES = ("점심시간", "저녁시간", "아침시간", "점심때", "저녁때", "아침때")
# 주체어가 아예 없는 '오늘 뭐 나와?'류를 위한 날짜어. 라우터가 dining으로 보냈는데 반박할
# 주체어조차 없으면 학식으로 본다 — 이게 없으면 새 대화의 첫 질문이 막힌다(실측).
_DATE_WORDS = ("오늘", "내일", "모레", "이번주",
               "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
# 식당 별칭 중 캠퍼스·기숙사 이름과 겹치는 것들(서캠·동캠·기숙사·청운숙·어학센터). 단독으로는
# 학식 신호로 인정하지 않는다 — '청운숙 통금 몇시야'가 '[기숙사 식당] 미운영'을, '동캠 어디야?'가
# 동캠 학생식당 위치를 답하던 문제(실측). 이름에 '식당'이 든 별칭(학생식당·서캠퍼스학생식당·
# 어학센터식당)은 _DINING_DOMAIN의 '식당'이 잡으므로 여기서 빠져도 그대로 통과한다.
_AMBIGUOUS_ALIASES = tuple(
    a for a in (*_ALIAS_ORDER, *_GUIDE_ONLY_ALIASES) if "식당" not in a
)


def _dining_domain_hit(compact: str) -> bool:
    """식당 별칭과 무관한 '학식 도메인 신호'가 있는가 (공백 제거된 문자열 기준)."""
    if any(w in compact for w in _DINING_DOMAIN):
        return True
    # 아래 두 신호는 요청어가 함께 있을 때만 인정한다('오늘 점심 뭐 나와' / '오늘 뭐 나와?').
    if not any(r in compact for r in _MENU_REQUEST):
        return False
    without_time = compact
    for phrase in _MEALTIME_PHRASES:
        without_time = without_time.replace(phrase, "")
    if any(m in without_time for m in _MEAL_WORDS):
        return True
    return (any(d in compact for d in _DATE_WORDS)
            and any(r in compact for r in _MENU_REQUEST_STRONG))


def _looks_like_dining(question: str, prev_question: str | None = None) -> bool:
    """이 질문을 학식 데이터로 답하는 게 맞는지 확인한다."""
    compact = (question or "").replace(" ", "")
    if _dining_domain_hit(compact):     # 도메인어 / 끼니어+요청어 / 날짜어+요청어
        return True
    if (any(a in compact for a in _AMBIGUOUS_ALIASES)
            and any(r in compact for r in _MENU_REQUEST)):
        return True         # '동캠기숙사 뭐야' — 겹치는 별칭은 요청어와 함께일 때만
    if any(m in compact for m in _MEAL_WORDS):
        return False        # 끼니어는 있는데 요청어가 없다 → 학식 질문 아님
    # 신호가 아예 없는 후속 질문('가격은?')만 직전 질문에서 물려받는다. 직전은 도메인어만
    # 인정한다 — '청운숙'·'동캠' 같은 별칭은 기숙사·캠퍼스 이름이기도 해서, 그것까지 인정하면
    # '청운숙 통금 몇시야' → '가격은?'이 학식 가격으로 샌다.
    if prev_question:
        return _dining_domain_hit(prev_question.replace(" ", ""))
    return False


async def answer_dining_question_with_meta(
    question: str, prev_question: str | None = None
) -> tuple[str, bool]:
    """(답변, 학식 데이터로 답할 수 있었는가) 반환.

    prev_question: 후속 질문에서 식당명이 생략됐을 때만 참고한다("기숙사 식당 밥 뭐야" →
      "가격은?"). 두 질문을 이어 붙이지 않고 '현재 질문에 없을 때만' 보충하는 이유는,
      이어 붙이면 "동캠 학식 뭐야" → "서캠은?"에서 두 식당명이 모두 잡혀 먼저 매칭된 쪽이
      이겨 버리기 때문이다(날짜·끼니도 같은 이유로 현재 질문 기준을 유지한다).

    두 번째 값이 False면 학식 데이터로 답할 수 없다는 뜻이고, 두 경우가 있다.
      (1) 애초에 학식 질문이 아니다 — 라우터가 잘못 보낸 것(_looks_like_dining이 거른다).
      (2) 학식 질문은 맞는데 학교 식당안내 표의 해당 칸이 비어 있다.
    (2)여도 학교에 정보가 없는 건 아니라서(기숙사 식당 가격 → 기숙사비 안내 문서의 식비
    내역) 호출부가 RAG로 한 번 더 찾아보게 한다.
    """
    if not _looks_like_dining(question, prev_question):
        print(f"[Dining] 학식 질문이 아님 → RAG 폴백 ('{question}')")
        return "", False

    intent = _resolve_intent(question)
    if intent == "menu":
        return await _answer_menu(question, prev_question), True
    return await _answer_guide(question, intent, prev_question)


async def answer_dining_question(question: str, prev_question: str | None = None) -> str:
    """완성된 답변 문자열만 필요할 때 쓰는 얇은 래퍼."""
    answer, _ = await answer_dining_question_with_meta(question, prev_question)
    return answer


def get_today_menu(restaurant: str | None = None) -> dict:
    """사이드바 '오늘의 학식' 위젯용 JSON 친화 dict 반환.

    구조화 데이터(끼니별 메뉴)를 그대로 내보낸다 — 채팅 답변(문자열)과 달리
    프론트에서 렌더링하기 좋게. get_menu_data()의 주 단위 캐시를 그대로 공유한다.
    """
    try:
        data = get_menu_data()
    except Exception as e:
        print(f"[Dining] 오늘 메뉴 조회 실패: {e}")
        return {"available": False}
    if not data:
        return {"available": False}

    rest = restaurant if (restaurant and restaurant in data) else _DEFAULT_RESTAURANT
    if rest not in data:
        rest = next(iter(data), None)
    menu = data.get(rest)
    if not menu:
        return {"available": False}

    date_key = date.today().strftime("%m.%d")
    try:
        month, day_n = date_key.split(".")
        weekday = _WEEKDAY_KO[date(date.today().year, int(month), int(day_n)).weekday()]
    except Exception:
        weekday = ""

    day_data = menu.days.get(date_key)
    meals = []
    if day_data:
        for col in menu.columns:
            items = day_data.get(col)
            if items:
                meals.append({"name": col, "items": items})

    return {
        "available": bool(meals),
        "restaurant": _display_name(rest),
        "date": date_key,
        "weekday": weekday,
        "meals": meals,
    }


def get_week_menu() -> dict:
    """학식 '더보기'용 — 이번 주 식당·요일·끼니 메뉴 + 안내(위치/운영/전화/가격) 병합.

    - 기숙사 3곳(국제·청운숙·동캠)은 메뉴가 동일하므로 1개로 dedup.
    - 각 식당에 안내 정보를 붙여, 메뉴가 없어도(방학 등) 위치·안내는 표시 가능.
      available은 '표시할 식당이 있는지', has_menu는 '식단 데이터가 있는지'로 구분.
    """
    try:
        data = get_menu_data()
    except Exception as e:
        print(f"[Dining] 주간 메뉴 조회 실패: {e}")
        return {"available": False, "has_menu": False, "restaurants": []}
    if not data:
        return {"available": False, "has_menu": False, "restaurants": []}

    try:
        guides = get_guide_data()
    except Exception as e:
        print(f"[Dining] 안내정보 조회 실패(무시): {e}")
        guides = {}

    restaurants = []
    dorm_added = False
    for name, menu in data.items():
        # 기숙사 3곳 메뉴 동일 → 1개만 유지 (dedup)
        if name in _SHARED_MENU_DORMS:
            if dorm_added:
                continue
            dorm_added = True

        days = []
        for date_key, day_data in menu.days.items():
            meals = []
            for col in menu.columns:
                items = day_data.get(col)
                if items:
                    meals.append({"name": col, "items": items})
            if meals:
                days.append({"date": date_key, "meals": meals})

        guide = guides.get(_MENU_TO_GUIDE_NAME.get(name, ""))
        restaurants.append({
            "name": _display_name(name),
            "location": guide.location if guide else None,
            "hours": guide.hours if guide else None,
            "phone": guide.phone if guide else None,
            "price": guide.price if guide else None,
            "days": days,
        })

    has_menu = any(r["days"] for r in restaurants)
    return {"available": bool(restaurants), "has_menu": has_menu, "restaurants": restaurants}


class DiningService:
    @staticmethod
    async def answer_dining_question(question: str) -> str:
        return await answer_dining_question(question)
