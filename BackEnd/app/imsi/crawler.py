from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

DEFAULT_NOTICE_URL = "https://tech.endicott.ac.kr/board/read.jsp?id=267227&code=tech0601"
REQUEST_TIMEOUT_SECONDS = 15


@dataclass
class CrawledPage:
    url: str
    title: str
    author: str | None
    published_at: str | None
    view_count: int | None
    content: str
    attachments: list[dict[str, str]] = field(default_factory=list)

    def to_document_text(self) -> str:
        lines = [
            f"제목: {self.title}",
            f"URL: {self.url}",
        ]
        if self.author:
            lines.append(f"작성자: {self.author}")
        if self.published_at:
            lines.append(f"작성일: {self.published_at}")
        if self.view_count is not None:
            lines.append(f"조회수: {self.view_count}")
        if self.attachments:
            attachment_names = ", ".join(item["name"] for item in self.attachments)
            lines.append(f"첨부파일: {attachment_names}")

        lines.extend(["", self.content])
        return "\n".join(lines).strip()

    def metadata(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "published_at": self.published_at,
            "view_count": self.view_count,
            "attachments": self.attachments,
        }


def fetch_page_html(url: str = DEFAULT_NOTICE_URL) -> str:
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def crawl_notice_page(url: str = DEFAULT_NOTICE_URL) -> CrawledPage:
    html = fetch_page_html(url)
    return parse_notice_page(html, url)


def parse_notice_page(html: str, url: str) -> CrawledPage:
    soup = BeautifulSoup(html, "html.parser")
    main = _find_notice_container(soup)

    title = _clean_text(_find_title(main) or _find_title(soup))
    if not title:
        title = soup.title.get_text(" ", strip=True) if soup.title else url

    metadata_text = _find_metadata_text(main)
    author = _extract_metadata(metadata_text, "작성자")
    published_at = _extract_metadata(metadata_text, "작성일")
    view_count = _extract_view_count(metadata_text)

    attachments = _extract_attachments(main, url)
    content = _extract_content(main, title)

    return CrawledPage(
        url=url,
        title=title,
        author=author,
        published_at=published_at,
        view_count=view_count,
        content=content,
        attachments=attachments,
    )


def _find_notice_container(soup: BeautifulSoup) -> Tag:
    # 우송대 표준 본문 컨테이너 (#headerTop, gnbWrap, .lnb, footer 자동 제외)
    body_con = soup.select_one("#bodyCon")
    if isinstance(body_con, Tag):
        return body_con

    board_read = soup.select_one(".board-read")
    if isinstance(board_read, Tag):
        return board_read

    headings = soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"])
    for heading in headings:
        if "졸업종합시험" in heading.get_text(" ", strip=True):
            ancestors = [
                parent
                for parent in heading.parents
                if isinstance(parent, Tag) and parent.name in {"article", "section", "div", "td", "table"}
            ]
            for ancestor in ancestors:
                text = ancestor.get_text(" ", strip=True)
                if "작성자" in text and "작성일" in text and len(text) > 300:
                    return ancestor
            if ancestors:
                return max(ancestors, key=lambda tag: len(tag.get_text(" ", strip=True)))

    candidates = soup.find_all(["article", "section", "div", "td"])
    best = max(candidates, key=lambda tag: len(tag.get_text(" ", strip=True)), default=soup)
    return best if isinstance(best, Tag) else soup


def _find_title(container: Tag | BeautifulSoup) -> str:
    for tag_name in ("h1", "h2", "h3", "h4", "strong", "b"):
        for tag in container.find_all(tag_name):
            text = tag.get_text(" ", strip=True)
            if "공지사항" in text:
                continue
            if len(text) >= 5:
                return text
    return ""


def _find_metadata_text(container: Tag | BeautifulSoup) -> str:
    for tag in container.find_all(["p", "div", "span", "td", "li"]):
        text = tag.get_text(" ", strip=True)
        if "작성자" in text and "작성일" in text:
            return _clean_text(text)
    return _clean_text(container.get_text(" ", strip=True))


def _extract_content(container: Tag, title: str) -> str:
    body = container.select_one(".board-body")
    if isinstance(body, Tag):
        container = body

    for removable in container.find_all(["script", "style", "noscript"]):
        removable.decompose()

    # 우송대 페이지 공통 불필요 요소 제거
    for removable in container.find_all(class_="content_top"):  # 제목+breadcrumb 영역
        removable.decompose()
    for removable in container.find_all(class_="path"):         # breadcrumb 단독 잔존 시
        removable.decompose()

    # rowspan 동아리 표 감지
    club_table = container.find("table", class_="tbl_skin2")
    if club_table:
        items = _parse_table_with_rowspan(club_table)
        if items:
            return "---ITEM---\n" + "\n---ITEM---\n".join(items)
            
    #HTML 요소 사이의 구분자를 \n\n으로 주어서 문단을 명확히 나눔
    text = container.get_text("\n\n", strip=True)
    lines = [_clean_text(line) for line in text.splitlines()]
    content_lines: list[str] = []
    skip_patterns = (
        "본문 바로가기",
        "커뮤니티",
        "공지사항",
        "작성자",
    )

    for line in lines:
        if not line:
            continue
        if line == title:
            continue
        if any(line.startswith(pattern) for pattern in skip_patterns):
            continue
        content_lines.append(line)

    content_lines = _trim_before_article_body(content_lines)
    #추출된 라인들을 다시 합칠 때도 \n\n을 써서 문단 형태를 보존
    content = "\n\n".join(content_lines)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content


def _extract_attachments(container: Tag, base_url: str) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    for link in container.find_all("a", href=True):
        name = _clean_text(link.get_text(" ", strip=True))
        href = str(link["href"])
        if not name:
            continue
        if "첨부" in name or re.search(r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?)$", name, re.I):
            attachments.append({"name": name, "url": urljoin(base_url, href)})
    return attachments


def _extract_metadata(text: str, key: str) -> str | None:
    match = re.search(rf"{key}\s*:\s*([^|]+)", text)
    return _clean_text(match.group(1)) if match else None


def _extract_view_count(text: str) -> int | None:
    match = re.search(r"조회수\s*:\s*([\d,]+)", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _clean_text(text: str) -> str:
    #\s+ 대신 [ \t\r\f\v]+ 를 사용하여 엔터(\n)는 보존하고 일반 스페이스바와 탭만 정리
    return re.sub(r"[ \t\r\f\v]+", " ", text.replace("\xa0", " ")).strip(" *")


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def _trim_before_article_body(lines: list[str]) -> list[str]:
    body_lines = lines
    for index, line in enumerate(body_lines[:3]):
        if line.startswith("[") or line.startswith("안녕하세요"):
            body_lines = body_lines[index:]
            break

    for index, line in enumerate(body_lines):
        if line in {"첨부파일", "목록", "이전글", "다음글"}:
            return body_lines[:index]
    return body_lines


def _parse_table_with_rowspan(table_tag: Tag) -> list[str]:
    """rowspan이 있는 표를 블록으로 변환 (헤더 동적 추출)"""
    items = []
    
    headers = ["항목1", "항목2", "항목3", "항목4"]
    # 헤더 찾기 시도
    thead = table_tag.find("thead")
    if thead:
        ths = thead.find_all("th")
        if ths:
            headers = [th.get_text(" ", strip=True) for th in ths]
    else:
        first_tr = table_tag.find("tr")
        if first_tr:
            ths = first_tr.find_all("th")
            if ths:
                headers = [th.get_text(" ", strip=True) for ths]
                
    # 안전장치로 길이를 4개로 맞춤
    while len(headers) < 4:
        headers.append(f"추가항목{len(headers)+1}")

    current_category = ""
    category_remaining = 0   # 현재 분야가 몇 행 더 이어지는지

    tbody = table_tag.find("tbody") or table_tag
    for row in tbody.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
            
        # 모든 셀이 th인 헤더 행은 건너뜀
        if all(c.name == "th" for c in cells):
            continue

        # rowspan 셀(분야)이 있는 행 — 첫 번째 td에 rowspan 속성
        if cells[0].get("rowspan"):
            current_category = cells[0].get_text(" ", strip=True)
            category_remaining = int(cells[0].get("rowspan")) - 1
            name_cell     = cells[1] if len(cells) > 1 else None
            activity_cell = cells[2] if len(cells) > 2 else None
            date_cell     = cells[3] if len(cells) > 3 else None

        # rowspan 없는 행 — 분야가 이어지는 중이면 3열, 새 분야면 4열
        elif category_remaining > 0:
            category_remaining -= 1
            name_cell     = cells[0] if len(cells) > 0 else None
            activity_cell = cells[1] if len(cells) > 1 else None
            date_cell     = cells[2] if len(cells) > 2 else None

        else:
            # rowspan 없이 분야가 직접 있는 행 (4열짜리)
            if len(cells) >= 4:
                current_category = cells[0].get_text(" ", strip=True)
                name_cell     = cells[1]
                activity_cell = cells[2]
                date_cell     = cells[3]
            else:
                name_cell     = cells[0] if len(cells) > 0 else None
                activity_cell = cells[1] if len(cells) > 1 else None
                date_cell     = cells[2] if len(cells) > 2 else None

        name     = name_cell.get_text(" ", strip=True)     if name_cell     else ""
        activity = activity_cell.get_text(" ", strip=True) if activity_cell else ""
        date     = date_cell.get_text(" ", strip=True)     if date_cell     else ""

        # 이름이 없는 행은 건너뜀 (thead 잔재 등)
        if not name or name == headers[1]:
            continue

        item = f"{headers[0]}: {current_category}\n{headers[1]}: {name}\n{headers[2]}: {activity}\n{headers[3]}: {date}"
        items.append(item)

    return items