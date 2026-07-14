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

def _remove_special_chars(text: str) -> str:
    """의미없는 특수문자 제거"""
    # 체크박스/불릿 마커 → 제거
    text = re.sub(r'[□■○●◎◆◇▶▷►▲△▼▽★☆]', '', text)
    # 구분선 (----, ====, ····) → 제거
    text = re.sub(r'^[\-=·_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 화살표 기호
    text = re.sub(r'[→←↑↓⇒⇐]', '', text)
    # 말줄임 구분선 (...., ……)
    text = re.sub(r'[.·]{4,}', '', text)
    return text

def _fix_pdf_line_breaks(text: str) -> str:
    """PDF 추출 시 단어 중간에 끊긴 줄바꿈 복구"""
    # 줄 끝이 하이픈으로 끊긴 경우: "수강신-\n청" → "수강신청"
    text = re.sub(r'-\n([가-힣a-zA-Z])', r'\1', text)
    # 줄 끝이 한글/영문으로 끝나고 다음 줄도 한글/영문으로 시작하면서
    # 다음 줄이 소문자나 한글로 시작하면 이어붙임 (문장 중간 줄바꿈)
    text = re.sub(r'([가-힣a-zA-Z])\n([가-힣a-z])', r'\1 \2', text)
    return text


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
