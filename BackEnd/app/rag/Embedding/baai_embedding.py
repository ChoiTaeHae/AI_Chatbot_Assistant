from app.core.config import settings


class BaaiEmbedding:

    def __init__(self) -> None:
        self.model_name = settings.EMBEDDING_MODEL
        self.device = settings.EMBEDDING_DEVICE
        self._model = None      # BGE-M3가 수 GB짜리라서 실제로 쓸 때만 메모리에 올림 

    @property
    def model(self):                #모델로드
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=False,
                device=self.device,
            )

        return self._model

    def embed_text(self, text: str) -> list[float]:     #텍스트 1개 → 벡터 1개
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:   #텍스트 여러 개 → 벡터 여러 개
        if not texts:
            return []

        result = self.model.encode(
            texts,
            return_dense=True,          # 밀집 벡터 사용 (유사도 검색용)
            return_sparse=False,        # 키워드 벡터 미사용
            return_colbert_vecs=False,  # ColBERT 벡터 미사용
        )

        dense_vectors = result["dense_vecs"]
        return [vector.tolist() for vector in dense_vectors]        #.tolist()로 변환.