"""
임베딩 기반 topic 자동 분류기

키워드 매칭 실패 시 질문을 임베딩해서 topic 대표벡터와 유사도를 비교,
가장 가까운 topic으로 라우팅한다. 임계값 미달이면 None 반환 (진짜 일반 질문).

각 topic마다 대표 질문 문장 여러 개를 임베딩한 뒤 평균 벡터를 사용한다.
키워드 나열보다 실제 질문 문장이 BGE-M3의 의미 공간에서 학생 질문과 가깝기 때문이다.
"""
from app.agents.intent import IntentType
from app.rag.Embedding import BaaiEmbedding

# topic별 대표 질문 문장 목록 (각각 임베딩 후 평균 벡터 사용)
TOPIC_PROTOTYPES: dict[IntentType, list[str]] = {

    IntentType.GRADUATION: [
        "졸업하려면 학점이 몇 점 필요한가요?",
        "졸업요건이 어떻게 되나요?",
        "전공필수 과목을 다 들어야 졸업할 수 있나요?",
        "교양필수 이수 학점은 몇 학점인가요?",
        "졸업까지 부족한 학점이 얼마나 되나요?",
        "졸업 가능 여부를 확인하고 싶어요",
        "이수조건을 알고 싶어요",
    ],

    IntentType.CAMPUS: [
        "도서관이 어디에 있나요?",
        "동아리 건물 위치가 어디예요?",
        "학과 사무실은 몇 층에 있나요?",
        "강의실을 찾고 싶어요",
        "식당은 어디에 있어요?",
        "체육관 위치가 어디인가요?",
        "W1 건물이 어디 있나요?",
        "캠퍼스 지도를 알고 싶어요",
        "보건의료과학관 위치 알려주세요",
    ],

    IntentType.RAG_GENERAL: [
        "장학금 신청 방법을 알고 싶어요",
        "수강신청은 언제 하나요?",
        "휴학 신청은 어떻게 하나요?",
        "기숙사 신청 방법이 어떻게 되나요?",
        "학사일정을 알려주세요",
        "성적 이의신청 방법을 알려주세요",
        "공결 처리는 어떻게 하나요?",
        "증명서 발급은 어디서 하나요?",
        "복학 신청 절차가 어떻게 되나요?",
        "학칙을 알고 싶어요",
        "특별학점 신청 방법은요?",
        "자퇴 절차가 어떻게 되나요?",
    ],

    IntentType.STUDENT_SUPPORT: [
        "오리엔테이션 일정이 어떻게 되나요?",
        "OT는 언제 하나요?",
        "학생지원 프로그램 신청하고 싶어요",
        "동아리 가입하려면 어떻게 해야 하나요?",
        "동아리 활동을 시작하고 싶어요",
        "동아리는 어떻게 등록해요?",
        "학생카드 신청 방법이 어떻게 되나요?",
        "카드 신청은 어디서 해요?",
        "학생증 카드 만들고 싶어요",
    ],

    IntentType.ROTC: [
        "ROTC 지원 방법이 어떻게 되나요?",
        "학군단에 어떻게 지원하나요?",
        "ROTC 선발 기준이 어떻게 되나요?",
        "ROTC 혜택이 뭐가 있나요?",
        "학군단 훈련 일정은 어떻게 되나요?",
        "사관후보생이 되려면 어떻게 해야 하나요?",
        "ROTC 장학금 혜택이 있나요?",
        "군사학 수업은 어떻게 운영되나요?",
    ],
}

# 유사도 임계값 — 이 값 이상이어야 해당 topic으로 라우팅
# BGE-M3 정규화 벡터 기준 코사인 유사도 (= 내적)
SIMILARITY_THRESHOLD = 0.40


def _dot(a: list[float], b: list[float]) -> float:
    """L2 정규화된 벡터의 내적 = 코사인 유사도"""
    return sum(x * y for x, y in zip(a, b))


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    """여러 임베딩 벡터를 평균낸 뒤 L2 정규화"""
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
        self._proto_vecs: dict[IntentType, list[float]] | None = None

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = BaaiEmbedding()
        return self._embedding

    def warmup(self) -> None:
        """서버 시작 시 topic 대표벡터 사전 계산 (첫 질문 지연 방지)

        모든 문장을 한 번에 임베딩한 뒤 topic별로 평균 벡터를 계산한다.
        """
        topic_list = list(TOPIC_PROTOTYPES.keys())
        sentence_ranges: list[tuple[int, int]] = []
        all_sentences: list[str] = []

        for topic in topic_list:
            start = len(all_sentences)
            all_sentences.extend(TOPIC_PROTOTYPES[topic])
            sentence_ranges.append((start, len(all_sentences)))

        all_vectors = self.embedding.embed_texts(all_sentences)

        self._proto_vecs = {}
        for topic, (start, end) in zip(topic_list, sentence_ranges):
            self._proto_vecs[topic] = _average_vectors(all_vectors[start:end])

        total = len(all_sentences)
        print(f"[TopicRouter] {len(topic_list)}개 topic, 총 {total}개 문장 임베딩 완료")

    def route(self, question: str) -> IntentType | None:
        """
        질문 임베딩 후 가장 유사한 topic 반환.
        모든 topic이 임계값 미달이거나 warmup 실패 시 None 반환.
        """
        intent, score = self.route_with_score(question)
        return intent if score >= SIMILARITY_THRESHOLD else None

    def route_with_score(self, question: str) -> tuple[IntentType | None, float]:
        """
        (최적 topic, 유사도 점수) 반환. 임계값 미달이어도 best topic을 반환함.
        warmup 실패 시 (None, 0.0) 반환.
        """
        if self._proto_vecs is None:
            try:
                self.warmup()
            except Exception as e:
                print(f"[TopicRouter] warmup 재시도 실패: {e}")
                return None, 0.0

        if self._proto_vecs is None:
            return None, 0.0

        q_vec = self.embedding.embed_text(question)

        best_topic: IntentType | None = None
        best_score = -1.0

        for topic, proto_vec in self._proto_vecs.items():
            score = _dot(q_vec, proto_vec)
            if score > best_score:
                best_score = score
                best_topic = topic

        print(f"[TopicRouter] 최고 유사도 → {best_topic} ({best_score:.3f})")

        return best_topic, best_score


# 싱글톤
topic_router = TopicRouter()
