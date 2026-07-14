import re

#region 정규식들
# 1. 조문 감지 및 분할용 정규식
ARTICLE_DETECT_PATTERN = re.compile(
    r"(?:^|\n)제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\([^)]*\))?",
    re.MULTILINE
)
ARTICLE_SPLIT_PATTERN = re.compile(
    r"(?:^|\n)(제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\([^)]*\))?)",
    re.MULTILINE
)

# 2. 장 감지용 정규식
CHAPTER_PATTERN = re.compile(
    r"(?:^|\n)(제\s*\d+\s*장\s+[^\n]+)", 
    re.MULTILINE
)

# 3. 항/호 단위(①, ②, 1., 2.) 분할용 정규식
# 원형 숫자 범위를 ①-⑳(U+2460-73) + ㉑-㉟(U+3251-5F) + ㊱-㊿(U+32B1-BF) 전체로 확장
# \d+\.\s 로 수정하여 날짜·일반문장 오탐 방지
CLAUSE_SPLIT_PATTERN = re.compile(r"\n(?=[\u2460-\u2473\u3251-\u325F\u32B1-\u32BF]|\d+\.\s)")
#endregion

def _split_sentences(text: str) -> list[str]:
    """줄 단위 문장 분리 — 한국어 공지문 최적화"""
    return [line.strip() for line in text.splitlines() if line.strip()]


def make_chunk(             # 최종 Chunk 생성기
    chunk_id: int,          # Chunk 번호
    chapter: str | None,    # 장 정보
    article: str | None,    # 조 정보
    text: str,              # 실제 정보
) -> dict:
    """메타데이터 및 RAG 최적화 임베딩 텍스트 생성"""
    path_parts = []     # 빈 리스트 생성

    if chapter:                     # chapter가 있으면
        path_parts.append(chapter)  # chapter="제1장 총칙" -> ["제1장 총칙"]
    if article:                     # article이 있으면
        path_parts.append(article)  # article="제1조 목적" -> ["제1조 목적"]

    path = " > ".join(path_parts)   # path 생성 후 리스트를 문자열로 합침 / 제1장 총칙 > 제1조 목적

    return {                   # 위의 정보 넣기
        "chunk_id": chunk_id,
        "chapter": chapter,
        "article": article,
        "path": path,
        "text": text,
        # 벡터 DB 임베딩용 (경로와 텍스트를 합쳐서 문맥 보존) *****
        "embedding_text": f"{path}\n{text}" if path else text,
    }


def smart_split(             # 실제 진입점
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
    min_length: int = 50,
    embed_fn=None,           # 시맨틱 청킹용: list[str] → list[list[float]]
) -> list[dict]:
    
    if "---ITEM---" in text:
        raw_chunks = split_by_separator(text, min_length=min_length)
    elif _has_markdown_table(text):
        # 마크다운 표가 있으면: 표 블록은 행(예: 과) 단위로, 나머지는 일반 청킹
        # → 표의 각 행이 자기 키(과명)를 달고 독립 청크가 됨 (여러 과 뭉침/과명 누락 방지)
        raw_chunks = []
        last_dept_chunk = None   # 직전 표 '과' 청크 — 페이지/블록 경계 넘는 연속 행 병합용
        for is_table, block in _find_table_blocks(text):
            if is_table:
                block_chunks = split_by_table(
                    block, chunk_size=chunk_size, min_length=min_length,
                    carry_chunk=last_dept_chunk,
                )
                raw_chunks.extend(block_chunks)
                # 이번 블록의 마지막 '과' 청크를 다음 블록 병합 대상으로 갱신
                for c in reversed(block_chunks):
                    if c.get("article"):
                        last_dept_chunk = c
                        break
            elif _has_structure(block):
                # 표 사이의 비표 블록도 헤딩/불릿 구조면 구조 청킹 (접수방법 등 리스트 중간 끊김 방지)
                # 표 행(split_by_table) 경로는 건드리지 않음 → 졸업 표 청킹 무영향
                raw_chunks.extend(split_by_structure(block, chunk_size=chunk_size, min_length=min_length))
            else:
                raw_chunks.extend(_chunk_generic(block, chunk_size, overlap, min_length, embed_fn))
    elif _has_structure(text):
        # 표는 없지만 헤딩/불릿 구조가 뚜렷한 문서(접수방법 안내 등)
        # → 헤딩+하위 불릿을 논리 단위로 유지하는 재귀 청킹 (리스트 중간 끊김 방지)
        raw_chunks = split_by_structure(text, chunk_size=chunk_size, min_length=min_length)
    else:
        raw_chunks = _chunk_generic(text, chunk_size, overlap, min_length, embed_fn)

    # 최종 반환 시 make_chunk를 통과시키며 순차적으로 chunk_id 부여
    return [
        make_chunk(
            chunk_id=i + 1,
            chapter=c.get("chapter"),
            article=c.get("article"),
            text=c["text"]
        )
        for i, c in enumerate(raw_chunks)
    ]

def _is_article_doc(text: str) -> bool:
    """조문(제N조) 문서인지 판단 — split_by_article 대상. (구조 청킹에서 제외용으로도 사용)"""
    articles = ARTICLE_DETECT_PATTERN.findall(text)
    total_lines = max(len(text.splitlines()), 1)
    return len(articles) >= 3 and (len(articles) / total_lines) > 0.05


def _chunk_generic(text: str, chunk_size: int, overlap: int, min_length: int, embed_fn) -> list[dict]:
    """표가 아닌 일반 텍스트 청킹 — 조문/시맨틱/문단 중 자동 선택 (smart_split의 기존 로직)."""
    if _is_article_doc(text):
        return split_by_article(text, min_length=min_length, chunk_size=chunk_size, overlap=overlap)     # 조문 단위 문서
    elif embed_fn is not None:
        return semantic_split(text, embed_fn, chunk_size=chunk_size, min_length=min_length)  # 시맨틱 청킹
    else:
        return split_by_paragraph(text, chunk_size=chunk_size, overlap=overlap, min_length=min_length)   # 일반 문서


# region 구조(헤딩/리스트) 인식 청킹 — 표 아닌 구조 문서용 (접수방법 안내 등)
# 재귀: 굵은 헤딩부터 자르고, 조각이 chunk_size를 넘으면 다음(세밀) 레벨로 내려가며 분할.
# 헤딩 + 그 아래 불릿을 한 논리 단위로 유지 → 리스트가 중간에서 끊기는 문제 방지.

# 재귀 분할 구분자 (굵음 → 세밀). lookahead(?=)로 헤딩을 다음 조각 앞에 남겨 '헤딩+내용'을 유지.
# 한국 공고문 위계: 1. > 가. > 1) > 가) > (1) > ○/■ > <소제목> > 불릿.
# 마침표 번호(1.)와 반괄호 번호(1))를 다른 레벨로 분리해야 '4. 대항목 + 1)~8) 소항목'이 한 덩어리로 유지됨.
_STRUCTURE_SEPARATORS = [
    r"(?=\n\s*\d{1,2}\.\s(?!\d))",   # 레벨1: 1. 2. (한두 자리+마침표) — 연도(2026.)·날짜(7. 10.) 오탐 방지
    r"(?=\n\s*[가-힣]\.\s)",           # 레벨2: 가. 나.
    r"(?=\n\s*\d+\)\s)",             # 레벨3: 1) 2) (숫자+반괄호)
    r"(?=\n\s*[가-힣]\)\s)",          # 레벨4: 가) 나)
    r"(?=\n\s*\(\d+\)\s)",           # 레벨5: (1) (2)
    r"(?=\n\s*[○◯■□▣]\s)",          # 레벨6: ○ ■ 마커 헤딩
    r"(?=\n\s*<[^>\n]{1,40}>)",       # 레벨7: <소제목>
    r"(?=\n\s*[•·▪◦▷▶☞*]\s)",        # 레벨8: 불릿
    r"\n\s*\n",                        # 레벨9: 문단
]

# 헤딩/불릿 마커 (구조 문서 판별용)
_HEADING_MARKER_RE = re.compile(
    r"\n\s*(?:[○◯■□▣•·▪◦▷▶☞]|\d+[.)]\s|[가-힣][.)]\s|\(\d+\)\s|<[^>\n]{1,40}>)"
)


def _has_structure(text: str) -> bool:
    """헤딩/불릿 구조가 뚜렷한 문서인지. 조문 문서는 제외(split_by_article로 감)."""
    if _is_article_doc(text):
        return False
    return len(_HEADING_MARKER_RE.findall(text)) >= 3


def _recursive_structure_split(text: str, sep_idx: int, chunk_size: int) -> list[str]:
    """굵은 구분자부터 자르고, 조각이 chunk_size 넘으면 다음 레벨로 재귀."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    if sep_idx >= len(_STRUCTURE_SEPARATORS):
        return split_by_length(text, chunk_size=chunk_size, overlap=0)   # 더 쪼갤 헤딩 없음 → 길이분할
    parts = [p.strip() for p in re.split(_STRUCTURE_SEPARATORS[sep_idx], text) if p.strip()]
    if len(parts) <= 1:
        return _recursive_structure_split(text, sep_idx + 1, chunk_size)  # 이 레벨 헤딩 없음 → 다음 레벨
    out: list[str] = []
    for p in parts:
        if len(p) <= chunk_size:
            out.append(p)
        else:
            out.extend(_recursive_structure_split(p, sep_idx + 1, chunk_size))
    return out


def _merge_short_pieces(pieces: list[str], chunk_size: int, min_length: int) -> list[str]:
    """짧은 조각/목록 항목을 인접 조각과 병합 (chunk_size 이내에서).

    - 한쪽이 min_length 미만이거나
    - 양쪽 다 '작은 조각'(목록 항목 수준)이면 병합
      → [붙임] 1.2.3.4. 같은 번호 목록이 큰 블록에서 흩어지지 않게 한 덩어리로 유지.
    접수방법/지원불가처럼 둘 다 큰 섹션이면 병합하지 않음(과합침 방지)."""
    small = max(min_length, chunk_size // 6)   # '작은 조각' 기준 (예: chunk_size 1200 → 200자)
    out: list[str] = []
    for p in pieces:
        if out and len(out[-1]) + len(p) + 1 <= chunk_size and (
            len(p) < min_length or len(out[-1]) < min_length
            or (len(p) < small and len(out[-1]) < small)
        ):
            out[-1] = out[-1] + "\n" + p
        else:
            out.append(p)
    return out


def split_by_structure(text: str, chunk_size: int = 1200, min_length: int = 50) -> list[dict]:
    """구조(헤딩/리스트) 인식 재귀 청킹. 헤딩+하위 불릿을 단위로 유지, 넘치면 하위 레벨로 분할."""
    pieces = _recursive_structure_split(text.strip(), 0, chunk_size)
    merged = _merge_short_pieces(pieces, chunk_size, min_length)
    return [{"chapter": None, "article": None, "text": p} for p in merged if p.strip()]
# endregion


# region 마크다운 표 청킹
def _is_table_row(line: str) -> bool:
    """| ... | ... | 형태의 표 행인지 판단 (파이프 2개 이상)."""
    line = line.strip()
    return line.startswith("|") and line.count("|") >= 2


def _is_sep_line(line: str) -> bool:
    """마크다운 표 구분선(|---|---|)인지 판단."""
    line = line.strip()
    return bool(re.match(r"^\|?[\s\-:|]+\|?$", line)) and "-" in line


def _has_markdown_table(text: str) -> bool:
    """표 행이 2개 이상 연속되거나 구분선이 있으면 마크다운 표로 간주.
    (구분선이 없는 추출물도 표로 인식하도록 완화)"""
    lines = text.split("\n")
    consec = 0
    for l in lines:
        if _is_table_row(l):
            consec += 1
            if consec >= 2:
                return True
        elif _is_sep_line(l):
            return True
        else:
            consec = 0
    return False


def _find_table_blocks(text: str) -> list[tuple[bool, str]]:
    """텍스트를 (is_table, block) 세그먼트로 분할.

    표 행/구분선이 연속되면 표 블록으로 묶되, 표 행 사이의 빈 줄은 표에 포함시킨다
    (pdfplumber가 페이지별로 표를 뽑아 \\n\\n 로 이어붙은 경우에도 한 표로 처리 →
    페이지를 넘어간 연속 행이 같은 블록에서 직전 과로 병합되도록)."""
    lines = text.split("\n")
    n = len(lines)
    segments: list[tuple[bool, str]] = []
    i = 0
    while i < n:
        if _is_table_row(lines[i]) or _is_sep_line(lines[i]):
            start = i
            i += 1
            while i < n:
                if _is_table_row(lines[i]) or _is_sep_line(lines[i]):
                    i += 1
                elif not lines[i].strip():
                    # 빈 줄: 이후에 표 행이 더 있으면 표에 포함, 아니면 표 종료
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and (_is_table_row(lines[j]) or _is_sep_line(lines[j])):
                        i = j
                    else:
                        break
                else:
                    break
            segments.append((True, "\n".join(lines[start:i])))
        else:
            start = i
            while i < n and not (_is_table_row(lines[i]) or _is_sep_line(lines[i])):
                i += 1
            block = "\n".join(lines[start:i])
            if block.strip():
                segments.append((False, block))
    return segments


# article(행 키)로 쓸 수 있는 첫 셀 최대 길이 — 이보다 길면 '키'가 아니라 내용으로 보고 article=None
_ARTICLE_MAXLEN = 50
# 헤더(컬럼 라벨) 셀 최대 길이 — 첫 줄 셀이 전부 이보다 짧아야 헤더로 인정
_HEADER_CELL_MAXLEN = 30


def _cells(line: str) -> list[str]:
    """마크다운 표 행에서 셀 리스트 추출."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def split_by_table(
    table_text: str,
    chunk_size: int = 1200,
    min_length: int = 50,
    carry_chunk: dict | None = None,
) -> list[dict]:
    """마크다운 표를 '행(레코드)' 단위로 청킹.

    - 첫 셀(키, 예: 과명)이 있으면 → 새 레코드 청크 시작, article = 키.
      단, 첫 셀이 너무 길면(키가 아니라 내용) article=None (긴 문단이 article로 오염 방지).
    - 첫 셀이 비면('|||' 패턴) → 페이지를 넘어온 연속 행 → 직전 레코드에 병합.
      블록 첫 행이 빈 셀이면 carry_chunk(직전 블록 레코드)에 병합 (페이지 경계 대비).
    - 표준 마크다운 표(헤더행 + |---| + 데이터)에서 헤더가 짧은 라벨성이면 →
      각 데이터 행 청크에 헤더를 주입해 컬럼 의미 보존 (다열 표 대응).
    - 구분선(|---|)은 무시. 레코드가 chunk_size를 넘으면 길이 분할.
    """
    raw = [l.strip() for l in table_text.split("\n") if l.strip()]
    if not raw:
        return [{"chapter": None, "article": None, "text": table_text.strip()}]

    # ── 헤더(컬럼 라벨) 감지 ──
    # 첫 줄 다음이 구분선이고, 첫 줄 셀이 모두 짧은 라벨성이면 헤더로 인정.
    # (졸업표처럼 첫 줄에 긴 셀이 있으면 실제 데이터 행이므로 헤더 아님 → 오탐 방지)
    header_prefix = ""
    body = raw
    if len(raw) >= 3 and _is_table_row(raw[0]) and _is_sep_line(raw[1]):
        h_cells = [c for c in _cells(raw[0]) if c]
        if len(h_cells) >= 2 and all(len(c) <= _HEADER_CELL_MAXLEN for c in h_cells):
            header_prefix = f"{raw[0]}\n{raw[1]}\n"
            body = raw[2:]

    # ── 작은 '데이터 그리드'(컬럼 헤더 있는 표)는 행별로 안 쪼개고 통째 한 청크 ──
    # 별표1(인정사유 표)·배점표처럼 헤더가 있는 작은 참조표는 행 파편화·주석 orphan을 막기 위해
    # 통으로 유지. 졸업 과별표는 '| 과명 | 요건 |' 헤더 없는 key-value 표라 header_prefix가 비어
    # 이 분기에 안 걸림 → 과별 행 분할 그대로(무영향).
    if header_prefix and len(table_text.strip()) <= chunk_size:
        return [{"chapter": None, "article": None, "text": table_text.strip()}]

    rows = [l for l in body if not _is_sep_line(l)]
    if not rows:
        return [{"chapter": None, "article": None, "text": table_text.strip()}]

    chunks: list[dict] = []
    cur_key: str | None = None
    cur_text: str | None = None
    carry = carry_chunk   # 블록 첫 행 연속 시 병합할 직전 블록의 레코드 청크

    def _flush() -> None:
        nonlocal cur_key, cur_text
        if cur_text is None:
            return
        if len(cur_text) >= min_length:
            if len(cur_text) <= chunk_size:
                chunks.append({"chapter": None, "article": cur_key, "text": cur_text})
            else:
                # 레코드가 너무 길면 길이 분할 (이어지는 조각에 헤더 재주입으로 문맥 유지)
                for k, part in enumerate(split_by_length(cur_text, chunk_size=chunk_size, overlap=0)):
                    if k > 0 and header_prefix and not part.lstrip().startswith("|"):
                        part = f"{header_prefix}{part}"
                    chunks.append({"chapter": None, "article": cur_key, "text": part})
        cur_key, cur_text = None, None

    for row in rows:
        cells = _cells(row)
        first = cells[0] if cells else ""
        if first:
            # 새 레코드 시작 — carry 종료
            _flush()
            carry = None
            # 첫 셀이 키라기엔 너무 길면 article로 안 씀 (긴 내용의 article 오염 방지)
            cur_key = first if len(first) <= _ARTICLE_MAXLEN else None
            cur_text = f"{header_prefix}{row}"
        else:
            # 빈 첫 셀 = 페이지 넘어온 연속 행
            cont = " ".join(c for c in cells if c).strip()
            if cur_text is not None:
                if cont:
                    cur_text = f"{cur_text} {cont}"
            elif carry is not None:
                # 블록 첫 행 연속 → 직전 블록 레코드에 물리 병합 (고아 방지)
                if cont:
                    carry["text"] = f"{carry['text']} {cont}"
            else:
                # 앞 레코드가 전혀 없으면 독립 청크(article 없음)
                cur_text = f"{header_prefix}{row}"
    _flush()
    return chunks
# endregion


# 조문 단위 문서
def split_by_article(text: str, min_length: int = 50, chunk_size: int = 1200, overlap: int = 150) -> list[dict]:
    parts = ARTICLE_SPLIT_PATTERN.split(text)

    if len(parts) <= 1:     # 조문 체크 / 패턴이 없으면 parts가 1개
        return split_by_paragraph(text, chunk_size=chunk_size, overlap=overlap, min_length=min_length)  # parts가 1개면 실행

    chunks: list[dict] = []    # 최종 청크 저장 리스트
    current_chapter = None     # 현재 장 / "제1장 총칙"을 만나면 / current_chapter="제1장 총칙"

    preamble = parts[0].strip()    # 첫 번째 조문 이전 내용 / 문서 제목, 개요 등
    chap_matches = list(CHAPTER_PATTERN.finditer(preamble))    # 서론 안에 장 제목이 있으면 current_chapter에 저장
    if chap_matches:
        current_chapter = chap_matches[-1].group(1).strip()
    
    if preamble and len(preamble) >= min_length:    # 서론이 min_length(50자) 이상이면 청크로 저장

        # _build_chunks: 길이 기준으로 자르는 헬퍼 함수
        chunks.extend(_build_chunks(preamble, current_chapter, "서론", chunk_size, overlap, min_length))

    for index in range(1, len(parts), 2):                           # 홀수 인덱스(1, 3, 5...)만 순회 → 조문 제목들
        title = parts[index].strip()                                # 조문 제목: "제1조(목적)"
        body = parts[index + 1] if index + 1 < len(parts) else ""   # 조문 내용: 다음 인덱스. 마지막 조문이면 빈 문자열

        # 조문 본문 안에 장 제목이 있는지 확인
        # 예: 본문 중간에 "제2장 학사과정"이 나오면 다음 조문부터 chapter 변경
        next_chap_matches = list(CHAPTER_PATTERN.finditer(body))
        next_chapter = current_chapter  # 일단 현재 장 유지
        
        new_chap_preamble = ""
        if next_chap_matches:
            first_match = next_chap_matches[0]
            last_match = next_chap_matches[-1]
            
            next_chapter = last_match.group(1).strip()
            new_chap_preamble = body[first_match.end():].strip()
            body = body[:first_match.start()].strip()

        chunk_text = f"{title}\n{body}".strip()     # 제목 + 본문 합치기

        # min_length(50자) 미만이면 너무 짧은 조문이므로 본문 추가는 건너뜀
        if len(chunk_text) >= min_length:
            # chunk_size(1200자) 초과 시 → 항/호 단위로 분할
            if len(chunk_text) > chunk_size:
                clauses = CLAUSE_SPLIT_PATTERN.split(body)   # CLAUSE_SPLIT_PATTERN: ①②③ 또는 1. 2. 3. 기준으로 분리
                # 항/호들을 chunk_size에 맞게 합치기
                # 제목 길이(-len(title)-10)만큼 빼서 합산 후 chunk_size 초과 방지
                merged_body_chunks = _merge_fragments(clauses, chunk_size - len(title) - 10, overlap)
                
                for sub_body in merged_body_chunks:
                    # 잘린 조각에 조문 제목 + (계속) 표시로 문맥 유지
                    chunks.append({
                        "chapter": current_chapter,
                        "article": title,
                        "text": f"{title} (계속)\n{sub_body}".strip()
                    })
            else:
                # 적당한 크기면 그대로 저장
                chunks.append({
                    "chapter": current_chapter,
                    "article": title,
                    "text": chunk_text
                })

        # 현재 조문 처리가 끝난 후, 새로운 장의 서론(안내문)이 있다면 청크로 추가 (데이터 유실 방지)
        if new_chap_preamble and len(new_chap_preamble) >= min_length:
            chunks.extend(_build_chunks(new_chap_preamble, next_chapter, "서론", chunk_size, overlap, min_length))

        # 다음 조문 처리 전에 chapter 업데이트
        current_chapter = next_chapter

    return _merge_article_chunks(chunks, chunk_size)


def _merge_article_chunks(chunks: list[dict], target: int) -> list[dict]:
    """짧은 조문 청크들을 인접끼리 target 이내로 병합.

    조문 하나당 청크 1개라 짧은 조(제1조 등)가 미니 청크로 흩어지는 것을 완화한다.
    - 같은 chapter 안에서만 병합
    - '(계속)'으로 이미 분할된 긴 조문끼리는 target를 넘으므로 자연히 안 합쳐짐
    - article은 병합 범위를 반영해 '제1조(목적) ~ 제5조(…)'로 표기(단일이면 그대로)
    """
    merged: list[dict] = []
    for c in chunks:
        prev = merged[-1] if merged else None
        if prev is not None and prev.get("chapter") == c.get("chapter") \
                and len(prev["text"]) + len(c["text"]) + 1 <= target:
            prev["text"] = f"{prev['text']}\n{c['text']}"
            prev["_last_art"] = c.get("article")
        else:
            merged.append({
                "chapter": c.get("chapter"),
                "article": c.get("article"),
                "text": c["text"],
                "_last_art": c.get("article"),
            })
    for m in merged:
        first, last = m["article"], m.pop("_last_art")
        if first and last and first != last:
            m["article"] = f"{first} ~ {last}"
    return merged


# 최상위 번호 항목 (1. 2. 3. ...) 감지용 패턴
_TOP_SECTION_PATTERN = re.compile(r"(?:^|\n)(\d+\.\s+\S)")


def semantic_split(
    text: str,
    embed_fn,
    chunk_size: int = 500,
    min_length: int = 50,
    breakpoint_percentile: int = 70,
) -> list[dict]:
    """임베딩 유사도 기반 시맨틱 청킹.

    인접 문장 간 코사인 거리가 상위 (100-percentile)%에 해당하면 청크 경계로 판단.
    chunk_size는 최대 크기 가드 — 시맨틱 경계가 없어도 초과 시 강제 분할.
    번호 항목(1. 2. 3.)이 2개 이상 있으면 먼저 구조적으로 분할 후 각 섹션에 시맨틱 청킹 적용.
    """
    import numpy as np

    # 최상위 번호 항목이 2개 이상이면 구조적으로 먼저 분할
    top_sections = re.split(r"(?=\n\d+\.\s)", text)
    if len(top_sections) >= 2:
        all_chunks: list[dict] = []
        for section in top_sections:
            section = section.strip()
            if not section:
                continue
            sub_chunks = _semantic_split_inner(section, embed_fn, chunk_size, min_length, breakpoint_percentile)
            all_chunks.extend(sub_chunks)
        return all_chunks

    return _semantic_split_inner(text, embed_fn, chunk_size, min_length, breakpoint_percentile)


def _semantic_split_inner(
    text: str,
    embed_fn,
    chunk_size: int = 500,
    min_length: int = 50,
    breakpoint_percentile: int = 70,
) -> list[dict]:
    """시맨틱 청킹 내부 구현"""
    import numpy as np

    sentences = _split_sentences(text)
    if not sentences:
        return []
    if len(sentences) <= 2:
        combined = "\n".join(sentences)
        return [{"chapter": None, "article": None, "text": combined}] if len(combined) >= min_length else []

    # 슬라이딩 윈도우(크기 3)로 전후 문맥 포함 임베딩 생성
    windowed = []
    for i in range(len(sentences)):
        start = max(0, i - 1)
        end = min(len(sentences), i + 2)
        windowed.append(" ".join(sentences[start:end]))

    print(f"[SemanticChunker] 문장 {len(sentences)}개 임베딩 시작")
    embeddings = embed_fn(windowed)
    print(f"[SemanticChunker] 임베딩 완료")

    # 인접 임베딩 간 코사인 거리 (거리 = 1 - 유사도)
    distances = []
    for i in range(len(embeddings) - 1):
        a = np.array(embeddings[i], dtype=np.float32)
        b = np.array(embeddings[i + 1], dtype=np.float32)
        sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
        distances.append(1.0 - sim)

    # 거리 분포에서 percentile 임계값 계산
    threshold = float(np.percentile(distances, breakpoint_percentile))
    print(f"[SemanticChunker] 청크 경계 임계값: {threshold:.4f} (percentile={breakpoint_percentile})")

    # 청크 경계 결정: 거리 > 임계값 이거나 최대 크기 초과 시 분할
    chunks = []
    current = [sentences[0]]
    current_len = len(sentences[0])

    for i, dist in enumerate(distances):
        nxt = sentences[i + 1]
        if dist > threshold or current_len + len(nxt) + 1 > chunk_size:
            text_chunk = "\n".join(current)
            if len(text_chunk) >= min_length:
                chunks.append({"chapter": None, "article": None, "text": text_chunk})
            current = [nxt]
            current_len = len(nxt)
        else:
            current.append(nxt)
            current_len += len(nxt) + 1

    if current:
        text_chunk = "\n".join(current)
        if len(text_chunk) >= min_length:
            chunks.append({"chapter": None, "article": None, "text": text_chunk})

    print(f"[SemanticChunker] {len(sentences)}문장 → {len(chunks)}청크")
    return chunks


def split_by_paragraph(text: str, chunk_size: int = 1200, overlap: int = 150, min_length: int = 50) -> list[dict]:

    # 빈 줄(\n\n 이상)을 기준으로 문단 분리
    # 예: "문단1\n\n문단2\n\n\n문단3" → ["문단1", "문단2", "문단3"]
    paragraphs = re.split(r"\n{2,}", text)

    # 분리된 문단들을 chunk_size에 맞게 합치기
    # 너무 짧은 문단들은 합치고, 너무 긴 문단은 자름
    merged_texts = _merge_fragments(paragraphs, chunk_size, overlap)
    
    chunks = []
    for text_chunk in merged_texts:
        # min_length(50자) 이상인 청크만 저장
        # chapter, article은 문단 단위 문서엔 없으므로 None
        if len(text_chunk) >= min_length:
            chunks.append({"chapter": None, "article": None, "text": text_chunk})
    
    # 문단 분리가 안 된 경우 (빈 줄이 없는 문서) → 길이 기준으로 강제 분할
    if not chunks:
        return _build_chunks(text, None, None, chunk_size, overlap, min_length)
        
    return chunks


def _merge_fragments(fragments: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    current_frags = []  # 현재 쌓고 있는 조각들
    current_len = 0     # 현재 합산 길이

    for frag in fragments:
        frag = frag.strip()
        if not frag: continue   # 빈 조각 건너뜀

        # 단일 조각이 chunk_size를 초과하는 경우 (거대 문단)
        if len(frag) > chunk_size:
            # 현재까지 쌓인 조각들 먼저 저장
            if current_frags:
                chunks.append("\n\n".join(current_frags))
                current_frags = []
                current_len = 0
            # 거대 문단은 _build_chunks로 강제 분할
            # _build_chunks는 dict 반환하므로 text만 추출
            chunks.extend([c["text"] for c in _build_chunks(frag, None, None, chunk_size, overlap, min_length=1)])
            continue

        # 현재 조각을 추가하면 chunk_size 초과 → 청크 확정
        if current_len + len(frag) + (2 if current_frags else 0) > chunk_size:
            if current_frags:
                chunks.append("\n\n".join(current_frags))

            # overlap 처리: 이전 청크의 마지막 조각들을 다음 청크 시작에 포함
            # 단어가 잘리지 않도록 조각 단위로 overlap 적용
            overlap_frags = []
            overlap_len = 0
            for i, p in enumerate(reversed(current_frags)):
                if i == 0:
                     # 가장 마지막 조각은 무조건 포함
                    overlap_frags.insert(0, p)
                    overlap_len += len(p)
                    continue
                
                # overlap 크기 안에 들어오면 앞에 추가
                if overlap_len + len(p) <= overlap:
                    overlap_frags.insert(0, p)
                    overlap_len += len(p) + 2   # \n\n 구분자 2자 포함
                else:
                    break   # overlap 초과 시 중단

            # overlap 조각들 + 현재 새 조각으로 다음 청크 시작
            current_frags = overlap_frags + [frag]
            # 길이 재계산: 각 조각 길이 + 구분자(\n\n=2자) * (조각수-1)
            current_len = sum(len(p) for p in current_frags) + (len(current_frags) - 1) * 2
        else:
            # chunk_size 안에 들어오면 현재 청크에 추가
            if current_frags:
                current_len += 2    # \n\n 구분자 2자 추가
            current_frags.append(frag)
            current_len += len(frag)

    # 루프 종료 후 마지막에 남은 조각들 저장
    if current_frags:
        chunks.append("\n\n".join(current_frags))

    return chunks


def _get_table_header(text: str, cut_pos: int) -> str:
    """cut_pos가 마크다운 표 내부에 있다면, 해당 표의 헤더(첫 2줄)를 반환합니다."""
    before = text[:cut_pos]
    lines = before.split("\n")
    header_lines = []
    
    for line in reversed(lines):
        line = line.strip()
        if not line:
            break
        if "|" in line:
            header_lines.insert(0, line)
        else:
            break
            
    # 완성된 블록의 두 번째 줄이 구분선(|---|)이라면 마크다운 표로 간주
    if len(header_lines) >= 2 and re.match(r"^\|?[\s\-:|]+\|?$", header_lines[1]) and "-" in header_lines[1]:
        return header_lines[0] + "\n" + header_lines[1] + "\n"
    return ""


def _build_chunks(text: str, chapter: str | None, article: str | None, chunk_size: int, overlap: int, min_length: int) -> list[dict]:
    # 연속 공백/탭을 스페이스 하나로 정규화 (표 유지를 위해 줄바꿈은 보존!)
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    # 3개 이상 연속된 줄바꿈은 2개로 축소
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    
    chunks = []
    start = 0
    current_table_header = ""

    while start < len(normalized):
        end = start + chunk_size

        # 마지막 조각 처리 (남은 텍스트가 chunk_size 이하)
        if end >= len(normalized):
            chunk = normalized[start:].strip()
            if len(chunk) >= min_length:
                chunks.append({"chapter": chapter, "article": article, "text": chunk})
            break
        
        # 단어 중간에서 자르지 않도록 줄바꿈 또는 공백 위치를 역방향 탐색
        cut = normalized.rfind("\n", start, end)
        if cut == -1 or cut <= start + overlap:
            cut = normalized.rfind(" ", start, end)
            if cut == -1 or cut <= start + overlap:
                cut = end

        chunk = normalized[start:cut].strip()
        
        # 이전 청크에서 잘린 표의 헤더가 있다면 현재 청크 맨 앞에 주입 (표 깨짐 방지)
        if current_table_header and not chunk.startswith(current_table_header.strip()):
            chunk = current_table_header + chunk

        if len(chunk) >= min_length:
            chunks.append({"chapter": chapter, "article": article, "text": chunk})

        # 다음 청크를 위해 현재 자르는 지점이 표 내부인지 확인
        current_table_header = _get_table_header(normalized, cut)

        # 다음 시작점 = cut - overlap (표 헤더가 주입되는 상황이면 중복 방지를 위해 overlap 최소화)
        actual_overlap = 0 if current_table_header else overlap
        next_start = cut - actual_overlap
        
         # 무한루프 방지: next_start가 현재 start 이하면 강제로 앞으로
        if next_start <= start:
            next_start = cut
        start = next_start

    return chunks


def split_by_length(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[str]:
    # _build_chunks를 호출하되 chapter, article 없이 순수 텍스트만 분할
    # min_length=1로 설정해서 아주 짧은 조각도 버리지 않음
    chunks = _build_chunks(
        text=text,
        chapter=None,
        article=None,
        chunk_size=chunk_size,
        overlap=overlap,
        min_length=1,
    )

     # _build_chunks는 dict 반환하므로 text 값만 추출해서 list[str]로 반환
    return [chunk["text"] for chunk in chunks]


def split_by_separator(text: str, separator: str = "---ITEM---", min_length: int = 50) -> list[dict]:
    """구분자 기준 항목별 청킹 — 동아리, 장학금 목록 등

    make_chunk 를 내부에서 직접 호출하지 않고 raw dict 만 반환.
    smart_split 의 마지막 make_chunk 루프에서 일괄 처리하므로
    chunk_id 부여·embedding_text 생성이 모든 경로에서 동일하게 적용됨.
    """
    raw_items = text.split(separator)
    chunks = []
    for item in raw_items:          # enumerate 제거 — chunk_id 는 smart_split 이 부여
        item = item.strip()
        if len(item) < min_length:
            continue
        chunks.append({"chapter": None, "article": None, "text": item})
    return chunks