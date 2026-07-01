import numpy as np


def _exp_normalize(x: np.ndarray) -> np.ndarray:
    b = x.max()
    y = np.exp(x - b)
    return y / y.sum()


class BgeReranker:

    def __init__(self):
        self._model = None
        self._tokenizer = None

    @property
    def _loaded(self):
        return self._model is not None

    def _load(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from app.core.config import settings

        model_path = settings.RERANKER_MODEL_PATH
        print(f"[Reranker] 모델 로딩: {model_path}")

        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self._model.eval()

        print("[Reranker] 로딩 완료")

    def rerank(
        self,
        question: str,
        documents: list[str],
    ) -> list[float]:
        import torch

        if not self._loaded:
            self._load()

        pairs = [[question, doc] for doc in documents]

        with torch.no_grad():
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
            scores = _exp_normalize(logits.numpy())

        print("[Reranker] rerank 완료")
        return scores.tolist()
