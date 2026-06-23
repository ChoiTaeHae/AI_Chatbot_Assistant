class BgeReranker:

    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker
            print("[Reranker] 모델 로딩")

            self._model = FlagReranker(
                "BAAI/bge-reranker-v2-m3",
                use_fp16=True,
            )

            print("[Reranker] 로딩 완료")

        return self._model

    def rerank(
        self,
        question: str,
        documents: list[str],
    ) -> list[float]:

        pairs = [
            [question, doc]
            for doc in documents
        ]

        scores = self.model.compute_score(pairs, normalize=True)

        print("[Reranker] rerank 완료")

        return scores