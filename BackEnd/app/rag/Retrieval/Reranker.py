import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


class BgeReranker:

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    @property
    def _loaded(self):
        return self._model is not None

    def _load(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from app.core.config import settings

        model_path = settings.RERANKER_MODEL_PATH
        # 설정이 cuda여도 GPU가 없으면 cpu로 폴백
        self._device = settings.RERANKER_DEVICE if torch.cuda.is_available() else "cpu"
        print(f"[Reranker] 모델 로딩: {model_path} (device={self._device})")

        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self._model.to(self._device)
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
            # 입력을 모델과 같은 device로 이동
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
            # numpy 변환 전 CPU로 (GPU 텐서는 .numpy() 불가)
            scores = _sigmoid(logits.cpu().numpy())

        print("[Reranker] rerank 완료")
        return scores.tolist()
