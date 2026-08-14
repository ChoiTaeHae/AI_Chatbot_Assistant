"""캠퍼스 날씨 조회 서비스 (OpenWeatherMap)

학사 문서에는 없는 실시간 데이터라 RAG로는 답할 수 없다. 외부 API를 직접 호출한다.

왜 캐시를 두는가
    날씨는 분 단위로 바뀌지 않는데 질문은 몰릴 수 있다(시연 중 여러 명이 동시에 묻는다).
    TTL 10분 캐시로 API 호출을 줄이고, 무료 티어 호출 한도(분당 60회)에 걸릴 여지를 없앤다.
    학식(dining)이 주 단위 캐시를 쓰는 것과 같은 이유이고, 주기만 날씨에 맞게 줄였다.

실패했을 때
    학식이 SSL 오류로 조용히 죽어 있던 사고가 있었다(2026-08-14, 크롤링 대상 인증서 문제).
    외부 의존은 반드시 눈에 보이게 실패해야 한다 → 예외를 삼키지 않고 found=False로 돌려
    호출부가 안내 문구를 내보내게 한다. 답변이 '빈 문자열'로 나가는 경우는 없다.

좌표
    우송대학교(대전 동구 자양동) 기준 한 지점만 본다. 캠퍼스가 동/서로 나뉘어 있지만
    직선거리 1km 안이라 날씨는 같다 — 캠퍼스별로 나눌 이유가 없다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from app.core.config import settings

# 우송대학교 (대전광역시 동구 동대전로 171)
WSU_LAT, WSU_LON = 36.3372, 127.4269

CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
# 대기질은 무료 티어에 포함된 별도 엔드포인트다(자외선지수는 One Call 3.0 유료라 제외).
AIR_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
REQUEST_TIMEOUT_SECONDS = 8

# 날씨는 10분 안에 의미 있게 바뀌지 않는다. 짧게 잡으면 호출만 늘고,
# 길게 잡으면 비가 오기 시작했는데 '맑음'이라고 답한다.
_CACHE_TTL_SECONDS = 600

KST = timezone(timedelta(hours=9))

_cache: dict[str, tuple[float, dict]] = {}   # {kind: (저장시각, 응답)}


def _get(url: str, kind: str) -> dict | None:
    """API 호출 + TTL 캐시. 키가 없거나 호출이 실패하면 None."""
    if not settings.OPENWEATHER_API_KEY:
        print("[Weather] OPENWEATHER_API_KEY 미설정 → 날씨 조회 건너뜀")
        return None

    hit = _cache.get(kind)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1]

    try:
        resp = requests.get(
            url,
            params={
                "lat": WSU_LAT, "lon": WSU_LON,
                "appid": settings.OPENWEATHER_API_KEY,
                "units": "metric",   # 섭씨
                "lang": "kr",        # 날씨 설명을 한국어로 받는다(직접 매핑할 필요가 없다)
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # requests의 HTTPError 메시지에는 요청 URL이 통째로 들어가고, 그 쿼리스트링에
        # appid(=API 키)가 들어 있다. 그대로 찍으면 `docker logs`를 읽을 수 있는 사람에게
        # 키가 노출된다 → 로그로 나가기 전에 가린다(미답변 질문 PII 마스킹과 같은 원칙).
        msg = str(e)
        if settings.OPENWEATHER_API_KEY:
            msg = msg.replace(settings.OPENWEATHER_API_KEY, "***")
        hint = ""
        if "401" in msg:
            # 신규 키는 발급 직후 최대 2시간 동안 401이 난다. 원인을 모르면 코드를 뒤지게
            # 되므로 로그에서 바로 알려 준다.
            hint = " (키 미활성화일 수 있음 — 발급 후 최대 2시간)"
        print(f"[Weather] {kind} 조회 실패: {type(e).__name__}: {msg}{hint}")
        # 만료된 캐시라도 있으면 그걸 쓴다 — 조금 오래된 날씨가 '모른다'보다 낫다.
        return hit[1] if hit else None

    _cache[kind] = (time.time(), data)
    return data


# OpenWeatherMap 조건 코드 → 한국어. lang=kr이 주는 번역을 쓰지 않는 이유는
# 기계번역이라 실제 출력이 어색하기 때문이다(실측: "실 비", "온흐림", "튼구름", "보통 비").
# 발표·사용자 화면에 그대로 나가면 무슨 뜻인지 되묻게 되므로 코드로 직접 매핑한다.
# 코드 체계: 2xx 뇌우 / 3xx 이슬비 / 5xx 비 / 6xx 눈 / 7xx 대기현상 / 800 맑음 / 80x 구름
_COND_EXACT = {
    800: "맑음", 801: "구름 조금", 802: "구름 많음", 803: "흐림", 804: "흐림",
    500: "약한 비", 501: "비", 502: "강한 비", 503: "매우 강한 비", 504: "폭우",
    511: "얼어붙는 비", 520: "약한 소나기", 521: "소나기", 522: "강한 소나기",
    600: "약한 눈", 601: "눈", 602: "많은 눈", 611: "진눈깨비",
    615: "비와 눈", 616: "비와 눈", 620: "약한 눈", 621: "눈", 622: "많은 눈",
    701: "옅은 안개", 711: "연기", 721: "실안개", 731: "먼지", 741: "안개",
    751: "모래", 761: "먼지", 762: "화산재", 771: "돌풍", 781: "토네이도",
}
_COND_PREFIX = {2: "뇌우", 3: "이슬비", 5: "비", 6: "눈", 7: "안개", 8: "흐림"}


def _desc(block: dict) -> str:
    w = (block.get("weather") or [{}])[0]
    code = w.get("id")
    if isinstance(code, int):
        if code in _COND_EXACT:
            return _COND_EXACT[code]
        # 표에 없는 코드는 백 자리로 큰 분류만 잡는다 — 새 코드가 생겨도 빈칸이 되지 않는다.
        by_prefix = _COND_PREFIX.get(code // 100)
        if by_prefix:
            return by_prefix
    # 코드가 없거나 모르는 체계면 API가 준 문장을 그대로 쓴다(빈칸보다 낫다).
    return w.get("description") or "정보 없음"


def _fmt_current(d: dict) -> str:
    main = d.get("main") or {}
    temp = main.get("temp")
    feels = main.get("feels_like")
    hum = main.get("humidity")
    wind = (d.get("wind") or {}).get("speed")
    now = datetime.now(KST).strftime("%m/%d %H:%M")

    lines = [f"**우송대 현재 날씨** ({now} 기준)", ""]
    lines.append(f"- 상태: {_desc(d)}")
    if temp is not None:
        s = f"- 기온: {temp:.1f}℃"
        if feels is not None and abs(feels - temp) >= 1:
            s += f" (체감 {feels:.1f}℃)"
        lines.append(s)
    if hum is not None:
        lines.append(f"- 습도: {hum}%")
    if wind is not None:
        lines.append(f"- 바람: {wind:.1f}m/s")

    # 비/눈이 실제로 오는 중일 때만 덧붙인다. 0을 늘 표시하면 잡음이 된다.
    rain = (d.get("rain") or {}).get("1h")
    snow = (d.get("snow") or {}).get("1h")
    if rain:
        lines.append(f"- 강수: 최근 1시간 {rain}mm ☔ 우산 챙기세요")
    if snow:
        lines.append(f"- 적설: 최근 1시간 {snow}mm ❄️")
    return "\n".join(lines)


def _fmt_forecast(d: dict, target: datetime, label: str) -> str | None:
    """3시간 간격 예보에서 target 날짜분만 골라 요약."""
    items = [
        it for it in (d.get("list") or [])
        if datetime.fromtimestamp(it["dt"], KST).date() == target.date()
    ]
    if not items:
        return None

    temps = [it["main"]["temp"] for it in items if it.get("main")]
    pops = [it.get("pop", 0) for it in items]
    # 그날을 대표하는 하늘 상태는 정오에 가장 가까운 시각으로 잡는다
    # (새벽 예보를 대표로 쓰면 '맑음'인 날이 '구름많음'으로 보인다).
    mid = min(items, key=lambda it: abs(datetime.fromtimestamp(it["dt"], KST).hour - 12))

    lines = [f"**우송대 {label} 날씨** ({target.strftime('%m/%d')})", ""]
    lines.append(f"- 상태: {_desc(mid)}")
    if temps:
        lines.append(f"- 기온: {min(temps):.0f}℃ ~ {max(temps):.0f}℃")
    if pops:
        top = max(pops)
        lines.append(f"- 강수확률: 최대 {int(top * 100)}%" + ("  ☔ 우산 챙기세요" if top >= 0.6 else ""))
    return "\n".join(lines)


_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]   # date.weekday() 인덱스 순서


def _fmt_week(d: dict) -> str | None:
    """5일치 예보를 요일별 한 줄로 접는다.

    3시간 간격 원본을 그대로 보여 주면 40줄이 되어 읽을 수 없다. 요일별로 묶어
    최저·최고 기온과 대표 하늘 상태만 남긴다 — 사용자가 실제로 알고 싶은 것은
    '무슨 요일에 뭘 입고 우산을 챙길지'다.

    풍속·습도·기압은 넣지 않는다. 표가 넓어지면 폰에서 가로로 잘리고,
    옷차림 판단에 쓰이지 않는 값이라 잡음이 된다.
    """
    by_day: dict = {}
    for it in (d.get("list") or []):
        day = datetime.fromtimestamp(it["dt"], KST).date()
        by_day.setdefault(day, []).append(it)
    if not by_day:
        return None

    lines = ["**우송대 주간 날씨**", "",
             "| 요일 | 날씨 | 기온 | 강수확률 |",
             "| --- | --- | --- | --- |"]
    for day in sorted(by_day):
        items = by_day[day]
        temps = [it["main"]["temp"] for it in items if it.get("main")]
        pops = [it.get("pop", 0) for it in items]
        # 그날의 대표 하늘 상태는 정오에 가장 가까운 예보로 잡는다
        # (새벽 값을 쓰면 맑은 날이 흐림으로 보인다).
        mid = min(items, key=lambda it: abs(datetime.fromtimestamp(it["dt"], KST).hour - 12))
        temp_s = f"{min(temps):.0f} ~ {max(temps):.0f}℃" if temps else "-"
        pop_s = f"{int(max(pops) * 100)}%" if pops else "-"
        lines.append(f"| {_WEEKDAY_KO[day.weekday()]} ({day.strftime('%m/%d')}) "
                     f"| {_desc(mid)} | {temp_s} | {pop_s} |")

    rainy = [day for day, items in by_day.items() if max(it.get("pop", 0) for it in items) >= 0.6]
    if rainy:
        days = ", ".join(f"{_WEEKDAY_KO[d.weekday()]}요일" for d in sorted(rainy))
        lines.append("")
        lines.append(f"☔ {days}에 비 소식이 있어요. 우산 챙기세요.")
    return "\n".join(lines)


# '이번주 날씨'처럼 여러 날을 한 번에 묻는 표현. 하루짜리 의도(_DAY_INTENT)보다 먼저 본다 —
# '이번주 내내 비 와?'에는 '내일'이 없지만, '주말'과 '오늘'이 함께 오는 문장은 주간으로 봐야 한다.
_WEEK_INTENT = ("이번주", "이번 주", "주간", "이번주내내", "일주일", "주중", "이번주말", "주말",
                "월화수목금", "요일별", "며칠")

# 질문에서 날짜 의도를 읽는다. 앞에 있는 것이 우선이라 '모레'를 '내일'보다 먼저 본다
# ('모레' 안에 '레'가 겹치지는 않지만, 순서를 명시해 두면 표현을 추가할 때 안전하다).
_DAY_INTENT = [
    (2, "모레", ("모레",)),
    (1, "내일", ("내일",)),
    (0, "오늘", ("오늘", "지금", "현재", "이따", "밖에")),
]


def _resolve_day(question: str) -> tuple[int, str]:
    q = question or ""
    for offset, label, keys in _DAY_INTENT:
        if any(k in q for k in keys):
            return offset, label
    return 0, "오늘"


# OpenWeatherMap 아이콘 코드 → 이모지. 이미지 URL을 쓰지 않는 이유는 외부 이미지 요청이
# 한 번 더 생기고(느려지고 차단될 수 있다) 다크모드에서 배경이 뜨기 때문이다.
# 끝의 d/n은 낮/밤이라 맑음만 해와 달로 나누고 나머지는 같은 그림을 쓴다.
_ICON_EMOJI = {
    "01d": "☀️", "01n": "🌙", "02d": "🌤️", "02n": "☁️",
    "03d": "⛅", "03n": "☁️", "04d": "☁️", "04n": "☁️",
    "09d": "🌧️", "09n": "🌧️", "10d": "🌦️", "10n": "🌧️",
    "11d": "⛈️", "11n": "⛈️", "13d": "❄️", "13n": "❄️",
    "50d": "🌫️", "50n": "🌫️",
}


def _emoji(block: dict) -> str:
    w = (block.get("weather") or [{}])[0]
    return _ICON_EMOJI.get(w.get("icon") or "", "🌡️")


# 미세먼지 등급은 한국 환경부 기준을 쓴다. OpenWeatherMap의 aqi(1~5)는 유럽 기준이라
# 같은 농도에서도 등급이 달라, 네이버·기상청을 함께 보는 학생에게 다른 값으로 보인다.
def _air_grade(pm: float | None, kind: str) -> str | None:
    if pm is None:
        return None
    cuts = (30, 80, 150) if kind == "pm10" else (15, 35, 75)
    for limit, label in zip(cuts, ("좋음", "보통", "나쁨")):
        if pm <= limit:
            return label
    return "매우나쁨"


def _hhmm(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, KST).strftime("%H:%M") if ts else None


def build_weather_card() -> dict | None:
    """화면 카드용 구조화 데이터. 실패하면 None(그때는 텍스트 답변만 나간다).

    텍스트 답변과 별개로 만드는 이유 — 카드가 없어도 답변은 그대로 나가야 한다.
    지도·학사일정 카드와 같은 원칙이고, 프론트가 카드를 못 그려도 대화는 성립한다.
    """
    cur = _get(CURRENT_URL, "current")
    if not cur:
        return None
    fc = _get(FORECAST_URL, "forecast") or {}
    air = _get(AIR_URL, "air") or {}

    main = cur.get("main") or {}
    sys_ = cur.get("sys") or {}
    comps = ((air.get("list") or [{}])[0].get("components") or {})

    # 오늘 최저/최고는 예보에서 뽑는다. 현재날씨 엔드포인트의 temp_min/temp_max는
    # '같은 시각 여러 관측소의 편차'라 우송대처럼 한 지점만 보면 둘이 같은 값으로 나온다
    # (실측: 30/30). 사용자가 기대하는 '오늘의 최저·최고'는 하루치 예보의 범위다.
    today = datetime.now(KST).date()
    today_temps = [
        it["main"]["temp"] for it in (fc.get("list") or [])
        if it.get("main") and datetime.fromtimestamp(it["dt"], KST).date() == today
    ]
    # 이미 지난 시간대는 예보에 없다. 지금 기온도 후보에 넣어야 오전에 이미 찍은
    # 최저값이 빠지지 않는다.
    now_temp = main.get("temp")
    if now_temp is not None:
        today_temps.append(now_temp)

    # 시간별 — 3시간 간격 8칸(24시간). 네이버는 1시간 간격이지만 무료 예보의 최소 단위가
    # 3시간이라 그대로 쓴다. 칸을 늘리면 폰에서 가로로 잘린다.
    hourly = []
    for it in (fc.get("list") or [])[:8]:
        t = datetime.fromtimestamp(it["dt"], KST)
        hourly.append({
            "time": f"{t.hour}시",
            "emoji": _emoji(it),
            "temp": round((it.get("main") or {}).get("temp", 0)),
            "pop": int(it.get("pop", 0) * 100),
        })

    # 내일 — 오전/오후를 나눠 보여 준다(네이버와 같은 방식). 하루 최대만 쓰면
    # 오후에만 비가 와도 종일 비로 읽힌다.
    tomorrow = None
    t_date = (datetime.now(KST) + timedelta(days=1)).date()
    t_items = [it for it in (fc.get("list") or [])
               if datetime.fromtimestamp(it["dt"], KST).date() == t_date]
    if t_items:
        am = [it for it in t_items if datetime.fromtimestamp(it["dt"], KST).hour < 12]
        pm = [it for it in t_items if datetime.fromtimestamp(it["dt"], KST).hour >= 12]
        temps = [it["main"]["temp"] for it in t_items if it.get("main")]
        mid = min(t_items, key=lambda it: abs(datetime.fromtimestamp(it["dt"], KST).hour - 12))
        tomorrow = {
            "date": t_date.strftime("%m.%d"),
            "emoji": _emoji(mid), "desc": _desc(mid),
            "min": round(min(temps)) if temps else None,
            "max": round(max(temps)) if temps else None,
            "am_pop": int(max((it.get("pop", 0) for it in am), default=0) * 100),
            "pm_pop": int(max((it.get("pop", 0) for it in pm), default=0) * 100),
        }

    return {
        "place": "동구 자양동",
        "date": datetime.now(KST).strftime("%m.%d"),
        "emoji": _emoji(cur),
        "desc": _desc(cur),
        "temp": round(main.get("temp", 0), 1),
        "feels_like": round(main.get("feels_like", 0), 1),
        "temp_min": round(min(today_temps)) if today_temps else None,
        "temp_max": round(max(today_temps)) if today_temps else None,
        "humidity": main.get("humidity"),
        "wind": round((cur.get("wind") or {}).get("speed", 0), 1),
        "pm10": _air_grade(comps.get("pm10"), "pm10"),
        "pm25": _air_grade(comps.get("pm2_5"), "pm25"),
        "sunrise": _hhmm(sys_.get("sunrise")),
        "sunset": _hhmm(sys_.get("sunset")),
        "hourly": hourly,
        "tomorrow": tomorrow,
    }


_SOURCE_NOTE = "\n\n_날씨 정보: OpenWeatherMap_"
_FAIL_NOTE = (
    "죄송해요, 지금은 날씨 정보를 불러오지 못했어요. 잠시 후 다시 물어봐 주세요.\n"
    "급하시면 기상청(weather.go.kr)에서 바로 확인하실 수 있어요."
)


def answer_weather_question(question: str) -> tuple[str, bool]:
    """(답변, 성공여부). 실패하면 안내 문구와 False를 돌려준다.

    호출부(agent_graph)가 found=False일 때 RAG로 넘기지 않고 이 문구를 그대로 쓰는 이유 —
    날씨는 문서에 없는 데이터라 RAG로 내려보내도 답이 나올 수 없고, 오히려 무관한 학사
    문서를 근거로 엉뚱한 답을 만들 위험만 생긴다.
    """
    # 여러 날을 묻는 표현이 먼저다 — '이번주 날씨'에 오늘 기온만 답하면 질문에 답한 게 아니다.
    if any(k in (question or "") for k in _WEEK_INTENT):
        data = _get(FORECAST_URL, "forecast")
        if not data:
            return _FAIL_NOTE, False
        body = _fmt_week(data)
        if body:
            return body + _SOURCE_NOTE, True
        return _FAIL_NOTE, False

    offset, label = _resolve_day(question)

    if offset == 0:
        data = _get(CURRENT_URL, "current")
        if not data:
            return _FAIL_NOTE, False
        return _fmt_current(data) + _SOURCE_NOTE, True

    data = _get(FORECAST_URL, "forecast")
    if not data:
        return _FAIL_NOTE, False
    target = datetime.now(KST) + timedelta(days=offset)
    body = _fmt_forecast(data, target, label)
    if not body:
        # 무료 예보는 5일치라 그 밖의 날짜는 데이터가 없다. '실패'가 아니라 '범위 밖'이므로
        # 이유를 밝힌다 — 같은 문구로 뭉뚱그리면 API 장애와 구분이 안 된다.
        return (f"{label} 날씨 예보는 아직 제공되지 않아요. "
                "오늘부터 5일 이내 날씨만 안내할 수 있어요."), True
    return body + _SOURCE_NOTE, True
