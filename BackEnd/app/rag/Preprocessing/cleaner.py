import re


# PDF가 커스텀 심볼 폰트로 그린 글리프를 유니코드 사설영역(PUA)으로 뽑은 것을 복구.
# - 성적 등급 폰트(공결 규정 등): 첫 글자=등급문자, 둘째 글자=부호 → A+/A0/B+ 로 복구
# - 그 외 매핑 없는 PUA(화살표·불릿 등 장식)는 공백으로 치환 (아래 normalize_pua)
_PUA_MAP = {
    "": "A", "": "B", "": "C", "": "D", "": "F",  # 등급 문자
    "": "+", "": "0",                                               # 등급 부호(+, 0)
    "": "·",                                                              # 가운뎃점/불릿
}


def _is_pua(ch: str) -> bool:
    o = ord(ch)
    return (0xE000 <= o <= 0xF8FF) or (0xF0000 <= o <= 0xFFFFD) or (0x100000 <= o <= 0x10FFFD)


def normalize_pua(text: str) -> str:
    """유니코드 사설영역(PUA) 문자 정규화.

    매핑된 코드포인트는 원래 문자로 복구(성적 등급 A+/A0 등),
    매핑 없는 잔여 PUA(깨진 화살표·심볼)는 공백으로 치환한다.
    (무조건 제거하면 등급 기호가 사라지므로 매핑 우선)"""
    if not any(_is_pua(c) for c in text):
        return text
    out = []
    for ch in text:
        if ch in _PUA_MAP:
            out.append(_PUA_MAP[ch])
        elif _is_pua(ch):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def preprocess_text(text: str) -> str:
    """RAG 인제스트 전 텍스트 정제 파이프라인"""
    text = normalize_pua(text)
    text = _normalize_whitespace_chars(text)
    text = _remove_page_numbers(text)
    text = _remove_document_headers(text)
    text = _remove_repeated_lines(text) # 고침 / ext로 받고 있었음.
    text = _collapse_whitespace(text)
    text = _remove_special_chars(text)
    text = _fix_pdf_line_breaks(text)
    return text


def _normalize_whitespace_chars(text: str) -> str:
    """HTML 엔티티 잔재, 비표준 공백 문자 정규화"""
    text = text.replace('\xa0', ' ')       # non-breaking space
    text = text.replace('\u200b', '')      # zero-width space
    text = text.replace('\u3000', ' ')     # 전각 공백
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    return text


def _remove_document_headers(text: str) -> str:
    """PDF 페이지 상단 반복 헤더 제거 (우송대 문서 형식)"""
    # "우송대학교 규정  문서명 [코드]" 형태의 페이지 헤더
    text = re.sub(r'^우송대학교\s+규정\s+.{1,60}$', '', text, flags=re.MULTILINE)
    # "우송대학교  부서명  내용" 형태
    text = re.sub(r'^우송대학교\s{2,}.{1,60}$', '', text, flags=re.MULTILINE)
    return text


def _remove_page_numbers(text: str) -> str:
    """단독 줄에 있는 페이지 번호 패턴 제거"""
    # "- 3 -", "- 12 -" 형식
    text = re.sub(r'^\s*-\s*\d+\s*-\s*$', '', text, flags=re.MULTILINE)
    # "3 / 12", "3/12" 형식
    text = re.sub(r'^\s*\d+\s*/\s*\d+\s*$', '', text, flags=re.MULTILINE)
    # 단독 숫자 한 줄 (1~4자리)
    text = re.sub(r'^\s*\d{1,4}\s*$', '', text, flags=re.MULTILINE)
    return text


def _collapse_whitespace(text: str) -> str:
    """과도한 공백/줄바꿈 정리"""
    # 줄 앞뒤 공백 제거
    lines = [line.strip() for line in text.splitlines()]
    text = '\n'.join(lines)
    # 3개 이상 연속 줄바꿈 → 2개로
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 같은 줄 내 공백 2개 이상 → 1개
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()

# 줄 맨 앞 마커(▶ 신청기한 등)는 장식이 아니라 섹션 헤딩 표시다. 청커가
# _STRUCTURE_SEPARATORS/_LINE_HEADING_RE로 바로 이 마커를 찾아 섹션 경계를 잡으므로
# 여기서 지우면 공고문이 섹션이 아니라 글자 수로 잘린다(제목만 든 고아 청크 발생).
# 청커가 아는 마커(○)로 통일해 보존하고, 문장 중간의 같은 기호만 장식으로 보고 제거한다.
_MARKER_CHARS = '□■○●◎◆◇▶▷►▲△▼▽★☆'
_LEAD_MARKER_RE = re.compile(rf'(?m)^([ \t]*)[{_MARKER_CHARS}][ \t]*')
_INLINE_MARKER_RE = re.compile(rf'[{_MARKER_CHARS}]')
_LEAD_SENTINEL = '\x00'   # 본문에 나올 수 없는 문자 — 줄머리 마커 임시 보호용


def _remove_special_chars(text: str) -> str:
    """의미없는 특수문자 제거 (줄 맨 앞 섹션 마커는 ○로 보존)"""
    # 체크박스/불릿 마커 → 줄머리는 보존, 그 외는 제거
    text = _LEAD_MARKER_RE.sub(lambda m: m.group(1) + _LEAD_SENTINEL, text)
    text = _INLINE_MARKER_RE.sub('', text)
    text = text.replace(_LEAD_SENTINEL, '○ ')
    # 구분선 (----, ====, ····) → 제거
    text = re.sub(r'^[\-=·_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 화살표 기호
    text = re.sub(r'[→←↑↓⇒⇐]', '', text)
    # 말줄임 구분선 (...., ……)
    text = re.sub(r'[.·]{4,}', '', text)
    return text

_VALUE_TOKEN_RE = re.compile(r'\d+\s*%|(?<!\S)-(?!\S)')   # 표 값 토큰: N%, 독립된 '-'(값 없음)


def _looks_like_table_row(line: str) -> bool:
    """표 행 신호: 마크다운 표(|)이거나 값 토큰(N%·독립 '-')이 2개 이상."""
    if line.lstrip().startswith('|'):
        return True
    return len(_VALUE_TOKEN_RE.findall(line)) >= 2


# 구조 헤딩으로 '시작'하는 줄 — 앞 문장과 병합하면 안 됨(조/장/항 헤딩이 앞줄에 흡수 방지).
# 예: "제3장 …\n제19조 …"를 붙이면 CHAPTER_PATTERN이 조문까지 장으로 삼켜 본문이 밀림.
_STRUCT_START_RE = re.compile(
    r'^\s*(?:'
    r'제\s*\d+\s*(?:조|장|절|관|항|호)(?:의\s*\d+)?'   # 제N조/제N장/제N조의2 …
    r'|부\s*칙'                                          # 부칙
    r'|\[별표'                                            # [별표 …]
    r'|[①-⑳]'                                            # ①②③ …
    r'|\d{1,2}\.\s'                                       # 1. 2.
    r'|[가-힣]\.\s'                                       # 가. 나.
    r'|\(\d+\)'                                           # (1) (2)
    r'|[○◯■□▣▷]'                                        # 구조 마커
    r')'
)


def _starts_with_structure(line: str) -> bool:
    """줄이 구조 헤딩(제N조·제N장·부칙·①·1.·가.·[별표]·마커)으로 시작하는지."""
    return bool(_STRUCT_START_RE.match(line))


def _fix_pdf_line_breaks(text: str) -> str:
    """PDF 추출 시 단어 중간에 끊긴 줄바꿈 복구. 표 행·구조 헤딩 줄은 붙이지 않아 구조를 보존."""
    # 1) 단어에 '붙은' 하이픈만 복구: "수강신-\n청" → "수강신청".
    #    표의 " - "(값 없음)은 앞이 공백이라 매칭 안 돼 그대로 보존됨.
    text = re.sub(r'(?<=[가-힣a-zA-Z])-\n(?=[가-힣a-zA-Z])', '', text)
    # 2) 문장 중간 줄바꿈 이어붙임 — 단, 앞/뒤가 표 행이거나 다음 줄이 구조 헤딩이면 건너뜀.
    lines = text.split('\n')
    if not lines:
        return text
    out = [lines[0]]
    for cur in lines[1:]:
        prev = out[-1]
        if (prev and cur and re.search(r'[가-힣a-zA-Z]$', prev) and re.match(r'[가-힣a-z]', cur)
                and not _looks_like_table_row(prev) and not _looks_like_table_row(cur)
                and not _starts_with_structure(cur)):   # 조/장/항 헤딩은 앞줄과 안 붙임
            out[-1] = prev + ' ' + cur       # 문장 줄바꿈 → 공백으로 이어붙임
        else:
            out.append(cur)
    return '\n'.join(out)


def _remove_repeated_lines(text: str, min_repeat: int = 3, max_len: int = 50) -> str:
    """전체 텍스트에서 반복되는 헤더/푸터 줄 제거"""
    from collections import Counter

    lines = text.splitlines()
    stripped = [l.strip() for l in lines]

    # 빈 줄 제외하고 등장 횟수 카운트
    counter = Counter(l for l in stripped if l)

    # 3회 이상 반복 + 50자 이하인 줄 → 헤더/푸터로 판단
    repeated = {
        line for line, cnt in counter.items()
        if cnt >= min_repeat and len(line) <= max_len
    }

    if not repeated:
        return text

    filtered = [l for l in lines if l.strip() not in repeated]
    return '\n'.join(filtered)
