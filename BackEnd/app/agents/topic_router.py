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

# topic 점수 = 그 topic 대표문장 중 질문과 가장 가까운 상위 K개의 평균 유사도.
# 평균 프로토타입(문장들을 벡터 1개로 뭉갬)은 "휴학 기간" 같은 짧은 질문에서 일반
# 기능어("기간")가 지배해 distinctive 단어("휴학")가 희석 → 엉뚱한 topic(schedule)으로
# 새는 문제가 있었다. 개별 문장 최대 유사도로 비교하면 leave 풀의 "휴학 기간이 얼마나
# 되나요?" 문장 하나가 살아나 정확히 매칭된다. 순수 max는 outlier 문장 1개에 과민하므로
# top-K 평균으로 완충한다(kNN k=K와 동일 원리).
_TOP_K = 3


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


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
        """서버 시작 시 topic별 대표문장 벡터 사전 계산.

        topic_data: DB에서 로드한 활성 topic 목록
          [{"name": str, "handler_type": str, "sentences": list[str]}, ...]
        문장이 없는 topic(general 등)은 벡터 생성을 건너뛴다.
        평균을 내지 않고 문장별 벡터를 그대로 보관한다(route_with_score에서 top-K 최대
        유사도로 비교하기 위해).
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
                "vecs": all_vectors[start:end],   # 개별 문장 벡터 전체 보관 (평균 안 함)
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
            vecs = info["vecs"]
            if not vecs:
                continue
            # 개별 문장 유사도 중 상위 K개 평균 (평균 프로토타입 대신)
            sims = sorted((_dot(q_vec, v) for v in vecs), reverse=True)
            k = min(_TOP_K, len(sims))
            score = sum(sims[:k]) / k
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
