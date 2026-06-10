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

    text = container.get_text("\n", strip=True)
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
    content = "\n".join(content_lines)
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
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip(" *")


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
