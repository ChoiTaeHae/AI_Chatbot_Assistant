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
GUIDE_URL = "https://www.wsu.ac.kr/page/index.jsp?code=scampus0806"
REQUEST_TIMEOUT_SECONDS = 15
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
        print(f"[Cafeteria] 메뉴 갱신 완료 (주차={current_week}, 식당={len(_cache)}개, 총 {total_days}일치)")

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
        print(f"[Cafeteria] 안내정보 갱신 완료 (주차={current_week}, 식당={len(_guide_cache)}개)")

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
}
_DEFAULT_RESTAURANT = "학생식당(서캠)"

# 끼니 키워드 → 컬럼명. 기숙사(조식/중식/석식)에만 매칭되고, 학생식당 코너명
# (소담상/한식 등)엔 자연히 안 걸려 전체 표시가 유지된다.
_MEAL_ALIASES: dict[str, str] = {
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
    for alias, real_name in _RESTAURANT_ALIASES.items():
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
    for alias, menu_name in _RESTAURANT_ALIASES.items():
        if alias in compact:
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


def _format_guide_answer(guide_name: str, guide: RestaurantGuide, intent: str, explicit: bool) -> str:
    value = getattr(guide, intent, None)
    label = _GUIDE_FIELD_LABEL[intent]

    if not value:
        line = f"{guide_name} {label} 정보가 없어요."
    else:
        line = f"[{guide_name}] {label}: {value}"

    lines = [line]
    if not explicit:
        lines.append("\n(다른 식당이 궁금하면 '동캠 학식', '기숙사 식당'처럼 물어봐 주세요!)")
    return "\n".join(lines)


# 기숙사 3곳(국제/청운숙/동캠)은 실측상 메뉴가 완전히 동일하다(같은 위탁업체). "기숙사"라고만
# 물으면 대표로 국제기숙사 데이터를 보여주는데, 라벨을 "[국제기숙사]"로만 표시하면 사용자가
# "청운숙/동캠도 같은 건가?"라고 의심할 수 있어 공통 메뉴임을 명시적으로 표시한다.
_SHARED_MENU_DORMS = {"국제기숙사", "청운숙기숙사", "기숙사(동캠)"}
_SHARED_MENU_LABEL = "기숙사(국제·청운숙·동캠 공통)"


def _display_name(restaurant: str) -> str:
    return _SHARED_MENU_LABEL if restaurant in _SHARED_MENU_DORMS else restaurant


def _format_answer(
    restaurant: str, date_key: str, menu: RestaurantMenu,
    explicit_restaurant: bool, meal_filter: str | None,
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
        lines = [
            f"{display} {date_label} 메뉴 정보가 없어요. "
            "주말·공휴일이거나 이번 주(월~일) 범위를 벗어난 날짜일 수 있어요."
        ]
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

    if not explicit_restaurant:
        lines.append("\n(다른 식당이 궁금하면 '동캠 학식', '기숙사 식단'처럼 물어봐 주세요!)")

    return "\n".join(lines)


async def _answer_menu(question: str) -> str:
    try:
        data = await asyncio.to_thread(get_menu_data)
    except Exception as e:
        print(f"[Cafeteria] 메뉴 조회 실패: {e}")
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    if not data:
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    restaurant, explicit = _resolve_restaurant(question, data)
    menu = data.get(restaurant)
    if not menu:
        return "학식 메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    date_key = _resolve_date_key(question)
    meal_filter = _resolve_meal(question, menu.columns)
    return _format_answer(restaurant, date_key, menu, explicit, meal_filter)


async def _answer_guide(question: str, intent: str) -> str:
    try:
        data = await asyncio.to_thread(get_guide_data)
    except Exception as e:
        print(f"[Cafeteria] 안내정보 조회 실패: {e}")
        return "학식 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    if not data:
        return "학식 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    guide_name, explicit = _resolve_guide_name(question)
    guide = data.get(guide_name)
    if not guide:
        return "학식 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요."

    return _format_guide_answer(guide_name, guide, intent, explicit)


async def answer_cafeteria_question(question: str) -> str:
    """학식 질문(메뉴/위치/전화/가격/운영시간)에 대한 완성된 답변 문자열을 반환한다."""
    intent = _resolve_intent(question)
    if intent == "menu":
        return await _answer_menu(question)
    return await _answer_guide(question, intent)


class CafeteriaService:
    @staticmethod
    async def answer_cafeteria_question(question: str) -> str:
        return await answer_cafeteria_question(question)
