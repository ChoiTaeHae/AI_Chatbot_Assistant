"""질문과 다운로드 후보 파일명 사이의 임베딩 유사도로 관련 파일만 추려낸다.

topic 전체 파일 목록을 통째로 LLM에게 보여주고 <FILES> 태그로 고르게 하면, 파일명에
"장학금"/"신청" 같은 공통 단어가 겹칠 때 로컬 소형 LLM이 무관한 파일까지 같이 골라버리는
문제가 있었다 (예: "푸른빛 희망 장학금" 질문에 "국가장학금 2유형" 파일까지 딸려나옴).
그래서 LLM에게 넘기기 전에 코드 레벨에서 후보를 1차로 좁힌다.

절대 유사도 기준(threshold)은 쓰지 않는다 — bge-m3 기준 한국어 행정 문서 제목들은
도메인이 같으면 무관한 제목끼리도 코사인 0.6대까지 나올 만큼 값이 뭉쳐 있어(실측),
절대 기준으로는 오탐/누락을 둘 다 잡기 어렵다. 대신 1등 파일 점수 대비 상대 마진으로
"1등과 비슷하게 가까운 파일(같은 건의 공고문+신청서 세트 등)"만 남긴다.
"""
import re
from pathlib import Path

from app.services.rag_service import rag_service

# 완전한 <FILES>…</FILES> 쌍
_FILES_PAIR_RE = re.compile(r"<FILES>.*?</FILES>", re.DOTALL)
# 닫히지 않고 열린 <FILES … (답변이 max_tokens로 잘려 닫는 태그가 안 나온 경우)
_FILES_OPEN_RE = re.compile(r"<FILES\b.*$", re.DOTALL)
# 태그 자체가 중간에 잘린 잔해: 답변 끝이 '<', '<F', … '<FILES' 로 끝남
_FILES_FRAG_RE = re.compile(r"<F(?:I(?:L(?:E(?:S)?)?)?)?$")
# 위 태그를 떼고 남는 열린 마크다운 링크 잔해: 줄 끝의 '[텍스트](' 또는 '- [텍스트]'
_DANGLING_LINK_RE = re.compile(r"\n?\s*-?\s*\[[^\]]*\]\(?\s*$")


# 마크다운 표 구분선 — '| --- | --- |', '|:---:|', '|---|' 등. 셀이 대시/콜론/공백뿐인 행.
# 앞의 개행까지 함께 잡아 줄을 통째로 제거한다(빈 줄이 남으면 표가 두 동강 난다).
_TABLE_SEP_RE = re.compile(r"\n?[ \t]*\|(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*(?=\n|$)")


def strip_table_separators(text: str) -> str:
    """마크다운 표의 구분선(| --- | --- |)만 제거한다. 헤더·데이터 행은 그대로 둔다.

    PDF 표를 마크다운으로 변환해 색인하다 보니 청크에 구분선이 그대로 들어있다(기숙사비
    안내 문서 기준 컨텍스트 하나에 파이프 172개, 구분선 13줄). 구분선은 순수 마크다운 문법이라
    정보가 0인데, 8B 모델에는 '이 형식을 따라 그려라'는 강한 신호가 돼서 답변에 '|--|'가
    그대로 새어 나온다(팀원 환경 실측). 값이 든 행은 표 구조 이해에 필요하므로 남기고,
    정보가 없는 구분선만 지워 따라 그릴 대상을 없앤다.
    """
    if not text or "|" not in text:
        return text
    cleaned = _TABLE_SEP_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


# 표의 '구분선 셀'(대시/콜론뿐) 판정 — 데이터 '-'(예: 인원 0명)와 구별하기 위해 셀 단위로 본다.
_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")


def _row_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    nonempty = [c for c in cells if c]
    return bool(nonempty) and all(_SEP_CELL_RE.match(c) for c in nonempty)


def _convert_table_block(block: list[str]) -> str | None:
    """여러 줄 마크다운 표(헤더 + | --- | 구분선 + 데이터행) → 행지향 텍스트.
    구분선이 없으면(표준 표가 아니면) None을 반환해 원본을 유지한다."""
    rows = [_row_cells(l) for l in block]
    sep = next((k for k, r in enumerate(rows) if _is_separator_row(r)), None)
    if not sep:                      # 구분선이 없거나 맨 앞이면 표준 표가 아님
        return None
    header = rows[sep - 1]
    data = rows[sep + 1:]
    if not data:
        return None
    out: list[str] = []
    for r in data:
        lead, pairs = None, []
        for idx, val in enumerate(r):
            if not val or _SEP_CELL_RE.match(val):   # 빈 셀·구분선 잔재는 건너뜀
                continue
            h = header[idx] if idx < len(header) else ""
            if lead is None and idx == 0:
                lead = val                            # 첫 열 값을 행의 앞머리로
            else:
                pairs.append(f"{h}: {val}" if h else val)
        if lead and pairs:
            out.append(f"- {lead} — " + " · ".join(pairs))
        elif lead:
            out.append(f"- {lead}")
        elif pairs:
            out.append("- " + " · ".join(pairs))
    return "\n".join(out) if out else None


def markdown_table_to_text(text: str) -> str:
    """참고 문서의 여러 줄 마크다운 표를 '행지향 텍스트'로 변환한다.

    작은 모델(8B)은 표를 '항목: 값'으로 풀라는 지시를 못 지키고 파이프 표를 그대로 복사하며
    한 줄로 뭉개(|- |-|) 답변을 망친다. 원본 청크의 표는 깨끗한 여러 줄 마크다운이므로
    (구분선이 명확한 | --- | 줄) LLM에 주기 전에 여기서 미리 텍스트로 바꿔 '복사할 표'를 없앤다.
    표가 아닌 파이프(구분선 잔재 등)는 이후 strip_table_separators가 정리한다."""
    if not text or "|" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        is_tbl = lines[i].strip().startswith("|") and lines[i].count("|") >= 2
        if is_tbl:
            j = i
            block: list[str] = []
            while j < n and lines[j].strip().startswith("|") and lines[j].count("|") >= 2:
                block.append(lines[j])
                j += 1
            converted = _convert_table_block(block)
            out.append(converted if converted is not None else "\n".join(block))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def strip_files_tag(text: str) -> str:
    """답변에서 <FILES> 태그를 제거한다. 파일 제안은 임베딩 필터로 확정하므로 LLM이 뽑은
    태그는 화면에서 지우기만 한다.

    기존엔 완전한 쌍만 지워, 답변이 max_tokens로 잘려 '…[휴학신청서류](<FILES>휴' 처럼
    닫는 태그 없이 끊기면 열린 태그가 그대로 화면에 노출됐다. 세 단계로 정리한다:
      1) 완전한 쌍 제거
      2) 닫히지 않은 열린 <FILES… 부터 끝까지 제거
      3) 태그 시작('<FIL' 등)만 잘려 남은 잔해 제거
    그리고 태그를 떼고 남는 '[파일명](' 같은 열린 마크다운 링크 잔해도 정리한다.
    """
    if not text:
        return text
    text = _FILES_PAIR_RE.sub("", text)
    text = _FILES_OPEN_RE.sub("", text)
    text = _FILES_FRAG_RE.sub("", text)
    text = _DANGLING_LINK_RE.sub("", text)
    return text.strip()


def clean_answer(text: str) -> str:
    """LLM 답변 최종 정리 — 화면에 새면 안 되는 잔해를 한 번에 제거한다.

    컨텍스트 단에서 이미 표 구분선을 지우지만(rag_service), 모델이 스스로 표를 그리려다
    '|--|'를 뱉는 경우가 있어 답변 쪽에도 같은 안전망을 둔다.
    """
    return strip_files_tag(strip_table_separators(text))

# 아래 세 값은 실제 bge-m3로 여러 케이스(휴학/장학금 등) 코사인 유사도를 측정해 정한 값 — 튜닝 가능.
# _MIN_TOP_SCORE는 '질문' 기준 0.55였으나 '답변' 기준으로 바꾸며 0.60으로 올렸다.
# 실제 답변 40건 실측: 서류 요구가 없는 기숙사비 답변은 0.45~0.59에 몰리고, 서류 제출을
# 요구하는 절차 답변(휴학 0.734 / 공결 0.654 / 근로장학 0.629)은 0.60 이상으로 갈렸다.
# (0.55면 정확도 75%, 0.60이면 85%로 최고)
_MIN_TOP_SCORE = 0.60   # 1등 파일조차 이 미만이면 확실히 관련된 파일이 없다고 보고 전부 제외
_MARGIN = 0.08          # 1등 점수 대비 이 폭 안에 든 파일만 "관련 있음"으로 간주
_MAX_CANDIDATES = 3     # 같은 건의 파일 세트(공고문+신청서 등)를 고려한 상한


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def match_relevant_files(text: str, files: list[str]) -> list[str]:
    """text(생성된 답변)와 의미적으로 가까운 파일만 남긴다.

    기준을 '질문'이 아니라 '답변'으로 두는 이유: 질문은 짧아 신호가 약하다. 실측에서
    '기숙사 비용 얼마야?'와 '외부인_기숙사_사용_동의서'가 0.559로, 무관한데도 진짜 파일
    요청('공결 신청서 양식 줘' 0.611)과 구간이 겹쳐 임계값으로 가를 수 없었다. 반면 답변은
    '휴학신청서와 구비서류를 제출해야 합니다'처럼 서류 요구가 문장으로 드러나, 서류를
    요구하지 않는 답변(기숙사비 0.45~0.59)과 요구하는 답변(0.60+)이 깨끗하게 갈린다.
    → 질문에 '서류'라는 단어가 없어도 답변이 서류를 요구하면 제안된다(의도한 동작).

    파일이 하나뿐이어도 검사한다. 예전엔 len(files)==1이면 무조건 반환했는데, 파일이 1개인
    토픽이 6개(dormitory·absence·drop_out 등)라 그 토픽 질문에는 무엇을 묻든 같은 파일이
    항상 딸려 나왔다("기숙사 비용?"에 외부인 사용 동의서 제안).
    임베딩 실패 시에는 필터링을 건너뛰고 원래 목록을 그대로 반환한다(기존 동작 유지).
    """
    if not files or not text:
        return []

    # 파일명은 공식 용어로 돼 있는데(예: '출석인정 요청서…') 질문·답변은 구어를 쓴다(예: '공결').
    # 이 간극 때문에 관련 파일이 0.587로 기준(0.60) 아래에 떨어져 제안되지 않았다(실측).
    # 검색어 딕셔너리를 반대 방향으로 적용해 제목에 구어 용어를 덧붙이면 0.693으로 통과한다.
    # (rag_general은 이 모듈을 지연 import 하므로 여기서도 지연 import 해 순환 참조를 피한다)
    try:
        from app.services.school.rag_general import expand_document_title
        names = [expand_document_title(Path(f).stem) for f in files]
    except Exception as e:                       # 확장 실패는 치명적이지 않다 — 원래 이름으로 진행
        print(f"[FileMatcher] 제목 확장 스킵: {e}")
        names = [Path(f).stem for f in files]
    try:
        vecs = rag_service.embedding.embed_texts([text, *names])
    except Exception as e:
        print(f"[FileMatcher] 임베딩 실패, 필터링 스킵: {e}")
        return files

    q_vec, file_vecs = vecs[0], vecs[1:]
    scored = sorted(
        ((f, _cosine(q_vec, v)) for f, v in zip(files, file_vecs)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    print("[FileMatcher] 후보 유사도: " + ", ".join(f"{Path(f).stem}={s:.3f}" for f, s in scored))

    top_score = scored[0][1]
    if top_score < _MIN_TOP_SCORE:
        print(f"[FileMatcher] 1등 점수({top_score:.3f})가 기준({_MIN_TOP_SCORE}) 미만 → 후보 없음")
        return []

    relevant = [f for f, score in scored[:_MAX_CANDIDATES] if score >= top_score - _MARGIN]
    return relevant
