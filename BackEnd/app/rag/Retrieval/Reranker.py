import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


class BgeReranker:

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._disabled = False   # 로딩 실패 시 True → 리랭킹 없이 벡터 검색만으로 degrade

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

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
            self._model.to(self._device)
            self._model.eval()
            print("[Reranker] 로딩 완료")
        except Exception as e:
            # 모델 폴더가 없거나 손상 등. 예전엔 여기서 예외가 그대로 터져 검색 파이프라인이
            # 통째로 죽었다(리랭커 하나로 RAG 전멸). 팀원 환경에 새 리랭커가 아직 없을 때 발생.
            # → 죽이지 않고 리랭킹만 끈다. 벡터 검색 결과를 그대로 써서 답변은 나오게(품질만 저하).
            self._disabled = True
            print(f"[Reranker] ⚠️ 로딩 실패 → 리랭킹 비활성화(벡터 검색만 사용): {type(e).__name__}: {e}")
            print(f"[Reranker] ⚠️ 모델 설치 필요: {model_path} "
                  f"(snapshot_download 'dragonkue/bge-reranker-v2-m3-ko')")

    def rerank(
        self,
        question: str,
        documents: list[str],
    ) -> list[float]:
        import torch

        if not self._loaded and not self._disabled:
            self._load()

        # 리랭커 비활성화(로딩 실패) → 벡터 검색 순서를 그대로 유지하는 점수를 반환한다.
        # retriever는 results를 '벡터 유사도순'으로 넘기므로, 입력 순서대로 완만히 감소하는
        # 점수(모두 SCORE_THRESHOLD 이상)를 주면 벡터 top-K가 그대로 컨텍스트가 된다.
        # 여러 쿼리로 rerank를 호출해 max로 합쳐도(동일 순서라) 순위가 안 흔들린다.
        if self._disabled:
            n = len(documents)
            return [1.0 - (i / n) * 0.4 for i in range(n)] if n else []

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
