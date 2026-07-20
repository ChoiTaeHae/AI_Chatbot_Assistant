"""우송대 학사일정 페이지(haksa_list.jsp) 전용 파서.

페이지 구조(2026 기준):
  <table>
    <caption>2026년 학부(과)의 월간 학사일정을 제공하는 표</caption>   → 학년도
    <tr><th>월</th><th>학부(과)</th><th>대학원</th></tr>
    <tr>
      <td>2026. 01</td>                                            → 달력 연/월(base)
      <td><ul class="dList"><li>12~16 : 1학기 전과 및 재입학 신청 기간</li>...</ul></td>  → 학부
      <td><ul class="dList"><li>2~9 : ...</li>...</ul></td>          → 대학원
    </tr>
    ...
  </table>
  (학년도별로 <table>이 여러 개)

각 <li>는 "날짜범위 : 이벤트명". 날짜범위는 월 헤더(base)를 기준으로 해석하되,
'M/D' 표기가 있으면 그 월을 명시로 쓴다. 월을 넘는 범위(6/29~3, 12/30~3, 29~7/3,
11/30~4 등)를 규칙으로 연/월 경계까지 복원한다.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.rag.Loader.web_crawler import fetch_page_html

# caption "2026년 학부(과)의 월간 학사일정을 제공하는 표" → 2026
_CAPTION_YEAR_RE = re.compile(r"(\d{4})\s*년")
# 월 셀 "2026. 01" / "2027.02" → (연, 월)
_MONTH_CELL_RE = re.compile(r"(\d{4})\s*[.\-]\s*(\d{1,2})")
# 우송대 CMS 콘텐츠 include: call("../page/haksa_list.jsp", "HaksaArea")
_CALL_INCLUDE_RE = re.compile(r"""call\(\s*['"]([^'"]+\.jsp[^'"]*)['"]""", re.I)


def _looks_like_schedule(html: str) -> bool:
    """학사일정 표가 실제로 들어있는 HTML인지 (caption의 '학사일정' + dList 마크업)."""
    return "학사일정" in html and "dList" in html


def fetch_schedule_html(url: str) -> tuple[str, str]:
    """학사일정 HTML을 가져온다. 표가 없으면(index.jsp?code=... 같은 '껍데기' 페이지)
    내부 call("...jsp") include를 해석해 실제 데이터 페이지를 대신 fetch한다.

    반환: (html, effective_url) — effective_url은 실제로 표를 가져온 URL.
    우송대 CMS는 콘텐츠를 call("../page/xxx.jsp", "영역id")로 주입하므로, 이 방식이면
    haksa_list.jsp를 직접 몰라도 index.jsp?code=campus0101 등으로도 동작한다."""
    html = fetch_page_html(url)
    if _looks_like_schedule(html):
        return html, url
    for m in _CALL_INCLUDE_RE.finditer(html):
        inner_url = urljoin(url, m.group(1))
        try:
            inner_html = fetch_page_html(inner_url)
        except Exception:
            continue
        if _looks_like_schedule(inner_html):
            print(f"[Schedule] 껍데기 페이지 → 내부 콘텐츠 해석: {inner_url}")
            return inner_html, inner_url
    return html, url   # 못 찾으면 원본 반환 (파싱 0건으로 graceful degradation)


def _parse_token(token: str, base_month: int) -> tuple[int, int]:
    """'12/30' → (12, 30);  '30' → (base_month, 30). 반환 (month, day)."""
    token = token.strip()
    if "/" in token:
        m, d = token.split("/", 1)
        return int(re.sub(r"\D", "", m)), int(re.sub(r"\D", "", d))
    return base_month, int(re.sub(r"\D", "", token))


def build_range(date_part: str, base_year: int, base_month: int) -> tuple[date | None, date | None]:
    """'6/29~3'·'23'·'11/30~4' 등 날짜 문자열 → (start, end). 실패 시 (None, None).

    연/월 경계 복원 규칙:
      - 시작 월이 base 월보다 크면 → 전년도 날짜가 이 칸으로 넘어온 것 (예: 1월 칸의 '12/30').
      - 끝이 시작보다 이르면 →
          · 끝에 월 표기(M/D)가 있으면 다음 해로 넘어간 것.
          · 월 표기가 없으면 다음 달로 넘어간 것 (예: 11월 칸의 '11/30~4' = 11/30~12/4).
    """
    date_part = (date_part or "").strip()
    try:
        if "~" in date_part:
            left, right = date_part.split("~", 1)
            right_explicit = "/" in right
            s_month, s_day = _parse_token(left, base_month)
            e_month, e_day = _parse_token(right, base_month)
            s_year = base_year - 1 if s_month > base_month else base_year
            e_year = base_year
            start = date(s_year, s_month, s_day)
            end = date(e_year, e_month, e_day)
            if end < start:
                if right_explicit:
                    end = date(e_year + 1, e_month, e_day)     # 명시월 역전 → 다음 해
                else:
                    nm, ny = (1, e_year + 1) if e_month == 12 else (e_month + 1, e_year)
                    end = date(ny, nm, e_day)                   # 무표기 역전 → 다음 달
            return start, end

        # 단일 일자
        s_month, s_day = _parse_token(date_part, base_month)
        s_year = base_year - 1 if s_month > base_month else base_year
        d = date(s_year, s_month, s_day)
        return d, d
    except (ValueError, IndexError):
        return None, None


def parse_schedule_html(html: str, url: str = "", keep_recent_years: int = 2) -> list[dict]:
    """학사일정 HTML → [{academic_year, track, event, start_date, end_date, raw, source_url}, ...]

    학년도별 <table>을 훑는다(학부/대학원 컬럼 모두). 날짜 파싱 실패 항목도 start/end=None으로
    보존해 정보 손실을 막는다(graceful degradation).

    keep_recent_years: 최근 N개 학년도만 유지(기본 2 = 올해+작년). 오래된 연도는 표기법이
      달라 파싱 실패가 잦고 "지금 무슨 기간" 질의에 노이즈라 버린다. 0 이하면 전부 유지."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []

    for table in soup.find_all("table"):
        caption = table.find("caption")
        cap_text = caption.get_text(" ", strip=True) if caption else ""
        m = _CAPTION_YEAR_RE.search(cap_text)
        if not m or "학사일정" not in cap_text:
            continue                                  # 학사일정 표가 아니면 skip
        academic_year = int(m.group(1))

        trs = table.find_all("tr")
        if not trs:
            continue

        # 헤더로 열 인덱스 → track 매핑
        header_cells = trs[0].find_all(["th", "td"])
        col_track: dict[int, str] = {}
        for idx, hc in enumerate(header_cells):
            htext = hc.get_text(" ", strip=True)
            if "대학원" in htext:
                col_track[idx] = "대학원"
            elif "학부" in htext or "학과" in htext:
                col_track[idx] = "학부"

        for tr in trs[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            mm = _MONTH_CELL_RE.search(cells[0].get_text(" ", strip=True))
            if not mm:
                continue                              # 월 셀 인식 실패 행 skip
            base_year, base_month = int(mm.group(1)), int(mm.group(2))

            for idx, cell in enumerate(cells):
                track = col_track.get(idx)
                if not track:                          # 월 컬럼(0) 또는 미매핑 컬럼
                    continue
                for li in cell.find_all("li"):
                    text = li.get_text(" ", strip=True)
                    if ":" not in text:
                        continue                       # "날짜 : 이벤트" 형식만
                    date_part, event = text.split(":", 1)
                    event = event.strip()
                    if not event:
                        continue
                    start, end = build_range(date_part, base_year, base_month)
                    out.append({
                        "academic_year": academic_year,
                        "track": track,
                        "event": event[:300],
                        "start_date": start,
                        "end_date": end,
                        "raw": date_part.strip()[:100],
                        "source_url": url,
                    })

    if keep_recent_years and keep_recent_years > 0 and out:
        recent = sorted({r["academic_year"] for r in out}, reverse=True)[:keep_recent_years]
        out = [r for r in out if r["academic_year"] in recent]

    return out
