"""
임베딩 기반 topic 자동 분류기

서버 시작 시 DB에서 topic 목록과 프로토타입 문장을 로드해 벡터화한다.
route_with_score()는 (topic_name, handler_type, score, all_scores) 튜플을 반환한다.
  - topic_name: DB Topic.name (Qdrant 필터 및 로그용)
  - handler_type: DB Topic.handler_type (agent_graph 라우팅용)
  - score: 코사인 유사도
"""
from app.rag.Embedding import BaaiEmbedding

SIMILARITY_THRESHOLD = 0.40


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    dim = len(vectors[0])
    avg = [sum(vectors[i][j] for i in range(n)) / n for j in range(dim)]
    norm = sum(x * x for x in avg) ** 0.5
    if norm > 0:
        avg = [x / norm for x in avg]
    return avg


class TopicRouter:
    def __init__(self, embedding: BaaiEmbedding | None = None) -> None:
        self._embedding = embedding
        # {topic_name: {"handler_type": str, "vec": list[float]}}
        self._proto_vecs: dict[str, dict] | None = None

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = BaaiEmbedding()
        return self._embedding

    def warmup(self, topic_data: list[dict]) -> None:
        """서버 시작 시 topic 대표벡터 사전 계산.

        topic_data: DB에서 로드한 활성 topic 목록
          [{"name": str, "handler_type": str, "sentences": list[str]}, ...]
        문장이 없는 topic(general 등)은 벡터 생성을 건너뛴다.
        """
        active = [t for t in topic_data if t.get("sentences")]
        if not active:
            self._proto_vecs = {}
            print("[TopicRouter] 분류 가능한 topic 없음 (sentences 비어있음)")
            return

        all_sentences: list[str] = []
        ranges: list[tuple[int, int]] = []

        for t in active:
            start = len(all_sentences)
            all_sentences.extend(t["sentences"])
            ranges.append((start, len(all_sentences)))

        all_vectors = self.embedding.embed_texts(all_sentences)

        self._proto_vecs = {}
        for t, (start, end) in zip(active, ranges):
            self._proto_vecs[t["name"]] = {
                "handler_type": t["handler_type"],
                "vec": _average_vectors(all_vectors[start:end]),
            }

        print(f"[TopicRouter] {len(self._proto_vecs)}개 topic, 총 {len(all_sentences)}개 문장 임베딩 완료")

    def route_with_score(self, question: str) -> tuple[str | None, str, float, dict[str, float]]:
        """(topic_name, handler_type, score, all_scores) 반환.

        all_scores: 전체 topic별 유사도 {topic_name: score}
                    — 이전 topic과의 상대 비교(topic 전환 판단)에 사용
        warmup 미완료 또는 매칭 없으면 (None, "general", 0.0, {}) 반환.
        """
        if self._proto_vecs is None:
            print("[TopicRouter] warmup 미완료 — general로 fallback")
            return None, "general", 0.0, {}

        if not self._proto_vecs:
            return None, "general", 0.0, {}

        q_vec = self.embedding.embed_text(question)

        best_name: str | None = None
        best_handler = "general"
        best_score = -1.0
        all_scores: dict[str, float] = {}

        for name, info in self._proto_vecs.items():
            score = _dot(q_vec, info["vec"])
            all_scores[name] = score
            if score > best_score:
                best_score = score
                best_name = name
                best_handler = info["handler_type"]

        print(f"[TopicRouter] 최고 유사도 → {best_name} / {best_handler} ({best_score:.3f})")
        return best_name, best_handler, best_score, all_scores

    def reload(self, topic_data: list[dict]) -> None:
        """어드민에서 topic 수정 후 라우터 즉시 갱신."""
        self.warmup(topic_data)


# 싱글톤
topic_router = TopicRouter()
