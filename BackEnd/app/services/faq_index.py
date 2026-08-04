"""학과생활 FAQ 시맨틱 매칭 (인메모리 인덱스).

어느 토픽에도 안 잡히는 질문을, 사람이 검수한 FAQ 답변에 질문↔질문 임베딩 유사도로 매칭한다.
- 매칭되면 faq.answer를 LLM 없이 그대로(verbatim) 반환 → 환각 0.
- 임계값 미만이면 None → 호출부가 기존 '못 찾음' 응답으로 폴백.
- 원본은 faq/faq_question 테이블(사람이 편집), 여기선 startup에 벡터를 메모리로만 파생한다.
  (수백~수천 규모: startup 재임베딩 1초 미만. 더 커지면 Qdrant로 이전 — faq_lookup만 교체)
"""
import math

from sqlalchemy import select

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import Faq, FaqQuestion
from app.services.rag_service import rag_service

# 질문↔질문 코사인 게이트. 미만이면 '답 못함'으로 넘긴다(틀린 답보다 '모름'이 안전).
# bge-m3 기준 패러프레이즈 0.6~0.85 / 무관 0.2~0.4 → 실제 로그로 튜닝할 것.
FAQ_THRESHOLD = 0.70

# 검색 근거가 약해(weak_evidence) LLM을 건너뛰고 FAQ를 그대로 내보내는 경로 전용 임계값.
# 그 경로는 오매칭이 곧 '교정 불가능한 확정 오답'이라 일반 조회보다 확실해야 한다.
# 실측(FAQ 42개 기준): FAQ가 정답인 질문 14건의 최저 점수는 0.771(엠티 언제가?)이고,
# FAQ가 오답인 질문 10건의 최고 점수는 0.711(내 졸업학점 얼마나 남았어?)로 두 집단이
# 0.06 간격으로 갈렸다. 0.75는 정상 14/14를 지키면서 오매칭 3건을 모두 막는다.
#   막힌 오매칭: 내 졸업학점 0.711 → 학점포기 / 수강신청 언제야 0.710 → 학사경고 /
#              졸업 신청 방법 0.707 → 학사경고
# (0.78은 엠티 0.771을 죽여 과하다)
FAQ_STRICT_THRESHOLD = 0.75

# [{"faq_id": int, "answer": str, "vec": list[float](정규화됨)}]
_index: list[dict] = []


def _normalize(v) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


async def warmup() -> None:
    """enabled인 faq_question을 전부 로드해 임베딩→정규화 벡터를 메모리에 상주.

    답변은 부모 faq.answer를 함께 보관한다(반환 시 그대로 사용). 서버 startup에서 임베딩
    인스턴스가 준비된 뒤 호출한다. 어드민이 표를 직접 편집하면 재시작으로 재색인된다.
    """
    global _index
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(FaqQuestion.text, FaqQuestion.faq_id, Faq.answer)
            .join(Faq, Faq.id == FaqQuestion.faq_id)
            .where(FaqQuestion.enabled == True, Faq.enabled == True)  # noqa: E712
        )).all()

    if not rows:
        _index = []
        print("[FAQ] 등록된 질문 없음 — 인덱스 비어있음")
        return

    texts = [r[0] for r in rows]
    vecs = rag_service.embedding.embed_texts(texts)
    _index = [
        {"faq_id": r[1], "answer": r[2], "vec": _normalize(v)}
        for r, v in zip(rows, vecs)
    ]
    print(f"[FAQ] {len(_index)}개 질문 임베딩 완료 (임계값 {FAQ_THRESHOLD})")


def faq_lookup(question: str, threshold: float | None = None) -> tuple[str, float] | None:
    """질문과 가장 유사한 FAQ를 찾아 (답변, 점수) 반환. 임계값 미만이면 None.

    threshold를 주면 그 값으로 판정한다(기본 FAQ_THRESHOLD). 검색 근거가 약해
    LLM을 건너뛰고 FAQ를 그대로 내보내는 경로는 오매칭이 곧 확정 오답이므로
    FAQ_STRICT_THRESHOLD처럼 더 높은 값을 쓴다.

    임베딩(블로킹) 호출을 하므로 async 핸들러에서는 run_in_executor로 감싼다(topic_router와 동일).
    """
    if not _index or not question:
        return None
    th = FAQ_THRESHOLD if threshold is None else threshold
    qv = _normalize(rag_service.embedding.embed_text(question))
    best_ans, best_score = None, -1.0
    for item in _index:
        s = sum(a * b for a, b in zip(qv, item["vec"]))
        if s > best_score:
            best_score, best_ans = s, item["answer"]
    if best_score >= th:
        print(f"[FAQ] 매칭 (score={best_score:.3f} ≥ {th}) → verbatim 답변")
        return best_ans, best_score
    print(f"[FAQ] 매칭 실패 (top score={best_score:.3f} < {th})")
    return None
