from app.core.config import settings


class BaaiEmbedding:
    """BAAI BGE-M3 dense embedding wrapper."""

    def __init__(self) -> None:
        self.model_name = settings.EMBEDDING_MODEL
        self.device = settings.EMBEDDING_DEVICE
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=self.device == "cuda",
                device="cpu",
            )

        return self._model

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:

        if not texts:
            return []

        result = self.model.encode(
            texts,
            return_dense=True,
            return_sparse=False,

            return_colbert_vecs=False
        )

        dense_vectors = result["dense_vecs"]
        return [vector.tolist() for vector in dense_vectors]