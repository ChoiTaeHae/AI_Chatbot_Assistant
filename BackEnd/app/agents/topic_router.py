"""
임베딩 기반 topic 자동 분류기

키워드 매칭 실패 시 질문을 임베딩해서 topic 대표벡터와 유사도를 비교,
가장 가까운 topic으로 라우팅한다. 임계값 미달이면 None 반환 (진짜 일반 질문).
"""
from app.agents.intent import IntentType
from app.rag.Embedding import BaaiEmbedding

# topic별 대표 문장 (임베딩 대상)
TOPIC_PROTOTYPES: dict[IntentType, str] = {

    IntentType.GRADUATION:
    """
    졸업 학점 졸업요건 전공필수 교양필수
    졸업가능 졸업조건
    """,

    IntentType.CAMPUS:
    """
    건물 위치 강의실 도서관 식당
    캠퍼스 학과사무실
    """,

    IntentType.RAG_GENERAL:
    """
    장학금 특별학점 오리엔테이션
    수강신청 휴학 복학 학사일정
    기숙사 생활관 증명서 학생증
    """
}

# 유사도 임계값 — 이 값 이상이어야 해당 topic으로 라우팅
# BGE-M3 정규화 벡터 기준 코사인 유사도 (= 내적)
SIMILARITY_THRESHOLD = 0.40


def _dot(a: list[float], b: list[float]) -> float:
    """L2 정규화된 벡터의 내적 = 코사인 유사도"""
    return sum(x * y for x, y in zip(a, b))


class TopicRouter:
    def __init__(self, embedding: BaaiEmbedding | None = None) -> None:
        self._embedding = embedding
        self._proto_vecs: dict[IntentType, list[float]] | None = None

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = BaaiEmbedding()
        return self._embedding

    def warmup(self) -> None:
        """서버 시작 시 topic 대표벡터 사전 계산 (첫 질문 지연 방지)"""
        topics  = list(TOPIC_PROTOTYPES.keys())
        texts   = list(TOPIC_PROTOTYPES.values())
        vectors = self.embedding.embed_texts(texts)
        self._proto_vecs = dict(zip(topics, vectors))
        print(f"[TopicRouter] {len(topics)}개 topic 프로토타입 준비 완료")

    def route(self, question: str) -> IntentType | None:
        """
        질문 임베딩 후 가장 유사한 topic 반환.
        모든 topic이 임계값 미달이거나 warmup 실패 시 None 반환.
        """
        if self._proto_vecs is None:
            try:
                self.warmup()
            except Exception as e:
                print(f"[TopicRouter] warmup 재시도 실패: {e}")
                return None

        if self._proto_vecs is None:
            return None

        q_vec = self.embedding.embed_text(question)

        best_topic: IntentType | None = None
        best_score = -1.0

        for topic, proto_vec in self._proto_vecs.items():
            score = _dot(q_vec, proto_vec)
            if score > best_score:
                best_score = score
                best_topic = topic

        print(f"[TopicRouter] 최고 유사도 → {best_topic} ({best_score:.3f})")

        return best_topic if best_score >= SIMILARITY_THRESHOLD else None


# 싱글톤
topic_router = TopicRouter()
