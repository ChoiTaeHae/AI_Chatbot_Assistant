from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

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
        # 임베딩되는 본문에는 검색에 도움되는 것만 포함.
        # URL·조회수는 의미 없는 토큰(https, 숫자)이라 임베딩에서 제외 → metadata() payload로만 보존.
        lines = [
            f"제목: {self.title}",
        ]
        if self.author:
            lines.append(f"작성자: {self.author}")
        if self.published_at:
            lines.append(f"작성일: {self.published_at}")
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


def fetch_page_html(url: str) -> str:
    # 학교 서버가 중간 인증서를 함께 보내지 않아 기본 검증이 실패한다.
    # app.core.http_client 가 빠진 중간 인증서를 채운 번들로 요청한다(검증 유지).
    from app.core.http_client import get as _get

    response = _get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def parse_notice_page(html: str, url: str) -> CrawledPage:
    soup = BeautifulSoup(html, "html.parser")
    main = _find_notice_container(soup)

    # 게시판 글(board-read)이면 글 제목을, 정보 페이지면 브레드크럼 페이지명을 제목으로.
    # (정보 페이지는 본문 소제목(h4)이 여럿이라 _find_title이 엉뚱한 소제목을 제목으로
    #  잡음 — 예: '주차안내' 페이지가 '정기권 등록 방법'으로. soup.title의
    #  '… > 페이지명 : 우송대학교'에서 페이지명을 뽑아 이를 방지.)
    if soup.select_one(".board-read"):
        title = _clean_text(_find_title(main) or _find_title(soup)) or _page_title_from_breadcrumb(soup)
    else:
        title = _page_title_from_breadcrumb(soup) or _clean_text(_find_title(main) or _find_title(soup))
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


def _page_title_from_breadcrumb(soup: BeautifulSoup) -> str:
    """soup.title('카테고리 > … > 페이지명 : 우송대학교')에서 페이지명만 추출.
    정보 페이지의 진짜 제목을 잡기 위함 — 본문 소제목(h4) 오인 방지."""
    if not getattr(soup, "title", None):
        return ""
    raw = soup.title.get_text(" ", strip=True)
    seg = re.split(r"\s*[:|]\s*", raw)[0]     # ' : 우송대학교' 등 사이트명 접미 제거
    if ">" in seg:
        seg = seg.split(">")[-1]              # 브레드크럼 마지막 항목 = 페이지명
    return _clean_text(seg)


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

    # 표(rowspan/colspan 포함)를 읽기순서 유지하며 '행 블록'으로 제자리 치환 (범용).
    # 각 행을 한 줄로 이어붙여 표를 하나의 텍스트 블록으로 만든다. 표 바로 앞의 제목(h태그)은
    # 그대로 두므로, 이후 구조 청킹이 '제목 + 표 블록'을 한 청크로 묶고(표=1청크),
    # 표가 chunk_size를 넘으면 제목을 각 조각에 전파하며 나눈다.
    for table in container.find_all("table"):
        rows = _parse_html_table(table)
        if rows:
            table.replace_with("\n" + "\n".join(rows) + "\n")
        else:
            table.decompose()

    # 제목 태그(h1~h6)를 구조 마커로 표기 → 평문 추출 후에도 '제목+본문'을 한 덩어리로
    # 청킹할 수 있게(split_by_structure가 헤딩을 인식). 부수효과로 크롤 문서가 semantic 대신
    # 구조 청킹을 타 임베딩 이중 계산이 사라져 속도도 개선됨.
    # 계층 구분: h1~h4=대분류(○, 굵은 레벨), h5~h6=하위(▷, 가는 레벨) → 청커가 대분류 경계를
    # 먼저 자르므로 '증명서 발급(h4)' 같은 대분류가 하위 항목과 안 섞이고 통째로 유지됨.
    for h in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        htext = h.get_text(" ", strip=True)
        if htext:
            marker = "○" if h.name in ("h1", "h2", "h3", "h4") else "▷"
            h.clear()
            h.append(f"{marker} {htext}")

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


def _parse_html_table(table_tag: Tag) -> list[str]:
    """HTML 표를 rowspan/colspan을 전개해 '헤더: 값' 행 블록 리스트로 변환.

    범용 — 열 수·병합 형태에 무관(동아리·주차·요금 등 어떤 표든). rowspan은 값을
    아래 행으로 물려주고, colspan은 여러 열로 펼쳐 그리드를 완성한 뒤 첫 행을 헤더로
    삼아 각 데이터 행을 '헤더: 값'으로 라벨링한다."""
    trs = table_tag.find_all("tr")
    if not trs:
        return []

    # 1) rowspan/colspan 전개해 그리드 완성
    grid: list[list[str]] = []
    spans: dict[int, list] = {}          # col -> [text, 남은 행 수]
    for tr in trs:
        cells = tr.find_all(["td", "th"])
        row: list[str] = []
        col = 0
        ci = 0
        while (col in spans) or (ci < len(cells)):
            if col in spans:             # 위 행 rowspan이 이 열을 차지
                text, rem = spans[col]
                row.append(text)
                if rem - 1 > 0:
                    spans[col] = [text, rem - 1]
                else:
                    del spans[col]
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            text = cell.get_text(" ", strip=True)
            try:
                cs = max(1, int(cell.get("colspan") or 1))
                rs = max(1, int(cell.get("rowspan") or 1))
            except (ValueError, TypeError):
                cs = rs = 1
            for _ in range(cs):
                row.append(text)
                if rs > 1:
                    spans[col] = [text, rs - 1]
                col += 1
        grid.append(row)

    # 2) 첫 행을 헤더로, 데이터 행을 '헤더: 값' 블록으로
    if len(grid) < 2:
        return [" ".join(c for c in r if c) for r in grid if any(v.strip() for v in r)]
    headers = grid[0]
    items: list[str] = []
    for row in grid[1:]:
        if row == headers:               # 반복된 헤더 행 건너뜀
            continue
        if not any(v.strip() for v in row):
            continue
        parts = []
        for idx, val in enumerate(row):
            h = headers[idx] if idx < len(headers) and headers[idx].strip() else f"항목{idx+1}"
            parts.append(f"{h}: {val}")
        items.append(" | ".join(parts))     # 한 행 = 한 줄 (제목 아래 표 블록으로 묶기 위함)
    return items