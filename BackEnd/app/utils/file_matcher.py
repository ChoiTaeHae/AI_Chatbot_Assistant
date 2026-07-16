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
from pathlib import Path

from app.services.rag_service import rag_service

# 아래 세 값은 실제 bge-m3로 여러 케이스(휴학/장학금 등) 코사인 유사도를 측정해 정한 값 — 튜닝 가능.
_MIN_TOP_SCORE = 0.55   # 1등 파일조차 이 미만이면 확실히 관련된 파일이 없다고 보고 전부 제외
_MARGIN = 0.08          # 1등 점수 대비 이 폭 안에 든 파일만 "관련 있음"으로 간주
_MAX_CANDIDATES = 3     # 같은 건의 파일 세트(공고문+신청서 등)를 고려한 상한


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def match_relevant_files(question: str, files: list[str]) -> list[str]:
    """question과 의미적으로 가까운 파일만 남겨 LLM에게 넘길 후보를 좁힌다.

    파일이 하나뿐이면 판단할 필요가 없으므로 그대로 반환한다(LLM이 질문 무관 여부만 판단).
    임베딩 실패 시에는 필터링을 건너뛰고 원래 목록을 그대로 반환한다(기존 동작 유지).
    """
    if not files:
        return []
    if len(files) == 1:
        return files

    names = [Path(f).stem for f in files]
    try:
        vecs = rag_service.embedding.embed_texts([question, *names])
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
