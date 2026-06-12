import re

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
CHAPTER_PATTERN = re.compile(r"(?:^|\n)(제\s*\d+\s*장\s+[^\n]+)", re.MULTILINE)

# 3. 항/호 단위(①, ②, 1., 2.) 분할용 정규식
CLAUSE_SPLIT_PATTERN = re.compile(r"\n(?=[①-⑳]|\d+\.)")


def make_chunk(
    chunk_id: int,
    chapter: str | None,
    article: str | None,
    text: str,
) -> dict:
    """[피드백 3] 메타데이터 및 RAG 최적화 임베딩 텍스트 생성"""
    path_parts = []

    if chapter:
        path_parts.append(chapter)
    if article:
        path_parts.append(article)

    path = " > ".join(path_parts)

    return {
        "chunk_id": chunk_id,
        "chapter": chapter,
        "article": article,
        "path": path,
        "text": text,
        # 벡터 DB 임베딩용 (경로와 텍스트를 합쳐서 문맥 보존)
        "embedding_text": f"{path}\n{text}" if path else text,
    }


def smart_split(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
    min_length: int = 50,
) -> list[dict]:
    articles = ARTICLE_DETECT_PATTERN.findall(text)
    total_lines = max(len(text.splitlines()), 1)
    
    # 조문 비율 체크
    if len(articles) >= 3 and (len(articles) / total_lines) > 0.05:
        raw_chunks = split_by_article(text, min_length=min_length, chunk_size=chunk_size, overlap=overlap)
    else:
        raw_chunks = split_by_paragraph(text, chunk_size=chunk_size, overlap=overlap, min_length=min_length)

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


def split_by_article(text: str, min_length: int = 50, chunk_size: int = 1200, overlap: int = 150) -> list[dict]:
    parts = ARTICLE_SPLIT_PATTERN.split(text)

    if len(parts) <= 1:
        return split_by_paragraph(text, chunk_size=chunk_size, overlap=overlap, min_length=min_length)

    chunks: list[dict] = []
    current_chapter = None

    preamble = parts[0].strip()
    chap_matches = list(CHAPTER_PATTERN.finditer(preamble))
    if chap_matches:
        current_chapter = chap_matches[-1].group(1).strip()
    
    if preamble and len(preamble) >= min_length:
        chunks.extend(_build_chunks(preamble, current_chapter, "서론", chunk_size, overlap, min_length))

    for index in range(1, len(parts), 2):
        title = parts[index].strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""

        next_chap_matches = list(CHAPTER_PATTERN.finditer(body))
        next_chapter = current_chapter
        
        if next_chap_matches:
            match = next_chap_matches[0]
            next_chapter = match.group(1).strip()
            body = body[:match.start()].strip()

        chunk_text = f"{title}\n{body}".strip()

        if len(chunk_text) < min_length:
            current_chapter = next_chapter
            continue

        if len(chunk_text) > chunk_size:
            clauses = CLAUSE_SPLIT_PATTERN.split(body)
            merged_body_chunks = _merge_fragments(clauses, chunk_size - len(title) - 10, overlap)
            
            for sub_body in merged_body_chunks:
                chunks.append({
                    "chapter": current_chapter,
                    "article": title,
                    "text": f"{title} (계속)\n{sub_body}".strip()
                })
        else:
            chunks.append({
                "chapter": current_chapter,
                "article": title,
                "text": chunk_text
            })

        current_chapter = next_chapter

    return chunks


def split_by_paragraph(text: str, chunk_size: int = 1200, overlap: int = 150, min_length: int = 50) -> list[dict]:
    paragraphs = re.split(r"\n{2,}", text)
    merged_texts = _merge_fragments(paragraphs, chunk_size, overlap)
    
    chunks = []
    for text_chunk in merged_texts:
        if len(text_chunk) >= min_length:
            chunks.append({"chapter": None, "article": None, "text": text_chunk})
            
    if not chunks:
        return _build_chunks(text, None, None, chunk_size, overlap, min_length)
        
    return chunks


def _merge_fragments(fragments: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    current_frags = []
    current_len = 0

    for frag in fragments:
        frag = frag.strip()
        if not frag: continue

        if len(frag) > chunk_size:
            if current_frags:
                chunks.append("\n\n".join(current_frags))
                current_frags = []
                current_len = 0
            # 내부 헬퍼 함수는 임시 dict를 반환하므로 text만 추출
            chunks.extend([c["text"] for c in _build_chunks(frag, None, None, chunk_size, overlap, min_length=1)])
            continue

        if current_len + len(frag) + (2 if current_frags else 0) > chunk_size:
            if current_frags:
                chunks.append("\n\n".join(current_frags))

            overlap_frags = []
            overlap_len = 0
            for i, p in enumerate(reversed(current_frags)):
                if i == 0:
                    overlap_frags.insert(0, p)
                    overlap_len += len(p)
                    continue
                
                if overlap_len + len(p) <= overlap:
                    overlap_frags.insert(0, p)
                    overlap_len += len(p) + 2
                else:
                    break

            current_frags = overlap_frags + [frag]
            current_len = sum(len(p) for p in current_frags) + (len(current_frags) - 1) * 2
        else:
            # 길이 계산 로직 오류 완벽 수정
            if current_frags:
                current_len += 2
            current_frags.append(frag)
            current_len += len(frag)

    if current_frags:
        chunks.append("\n\n".join(current_frags))

    return chunks


def _build_chunks(text: str, chapter: str | None, article: str | None, chunk_size: int, overlap: int, min_length: int) -> list[dict]:
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0

    while start < len(normalized):
        end = start + chunk_size
        if end >= len(normalized):
            chunk = normalized[start:].strip()
            if len(chunk) >= min_length:
                chunks.append({"chapter": chapter, "article": article, "text": chunk})
            break

        cut = normalized.rfind(" ", start, end)
        if cut == -1 or cut <= start + overlap:
            cut = end

        chunk = normalized[start:cut].strip()
        if len(chunk) >= min_length:
            chunks.append({"chapter": chapter, "article": article, "text": chunk})

        # 무한 루프 완벽 방지
        next_start = cut - overlap
        if next_start <= start:
            next_start = cut
        start = next_start

    return chunks


def split_by_length(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[str]:
    chunks = _build_chunks(
        text=text,
        chapter=None,
        article=None,
        chunk_size=chunk_size,
        overlap=overlap,
        min_length=1,
    )

    return [chunk["text"] for chunk in chunks]