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
    else:
        articles = ARTICLE_DETECT_PATTERN.findall(text)    # 정규식에 맞는 것 전부 찾음
        total_lines = max(len(text.splitlines()), 1)       # 줄 단위 분리

        # 조문 비율 체크
        if len(articles) >= 3 and (len(articles) / total_lines) > 0.05:     # 비율 체크 후 판단
            raw_chunks = split_by_article(text, min_length=min_length, chunk_size=chunk_size, overlap=overlap)     # 조문 단위 문서
        elif embed_fn is not None:
            raw_chunks = semantic_split(text, embed_fn, chunk_size=chunk_size, min_length=min_length)  # 시맨틱 청킹
        else:
            raw_chunks = split_by_paragraph(text, chunk_size=chunk_size, overlap=overlap, min_length=min_length)   # 일반 문서

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



    return chunks


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