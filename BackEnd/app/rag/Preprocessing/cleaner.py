import re


def preprocess_text(text: str) -> str:
    """RAG 인제스트 전 텍스트 정제 파이프라인"""
    text = _normalize_whitespace_chars(text)
    text = _remove_page_numbers(text)
    ext = _remove_repeated_lines(text)
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
