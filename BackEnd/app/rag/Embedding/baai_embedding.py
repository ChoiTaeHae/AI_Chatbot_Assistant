from app.core.config import settings


class BaaiEmbedding:

    def __init__(self) -> None:
        self.model_name = settings.EMBEDDING_MODEL    # config에서 모델 이름 가져옴 (예: "BAAI/bge-m3")
        self.device = settings.EMBEDDING_DEVICE       # config에서 디바이스 가져옴 (예: "cuda" or "cpu")
        self._model = None      # 처음엔 None, 실제로 쓸 때만 로드 (BGE-M3가 수 GB짜리라서 실제로 쓸 때만 메모리에 올림)

    @property
    def model(self):
        # 처음 접근할 때만 모델 로드, 이후엔 캐시된 _model 반환
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            # VRAM 여유 확인 후 device 결정
            # LLM(~5GB) + BGE-M3(~2.5GB) = 7.5GB → RTX 3070 8GB 아슬아슬
            # VRAM 여유가 1.5GB 이상이면 CUDA, 아니면 CPU로 fallback
            actual_device = "cpu"
            if self.device == "cuda":
                try:
                    import torch
                    # mem_get_info()[0] = 현재 여유 VRAM (bytes) → GB 변환
                    free_vram = torch.cuda.mem_get_info()[0] / 1024**3
                    actual_device = "cuda" if free_vram >= 1.5 else "cpu"
                    print(f"[Embedding] VRAM 여유: {free_vram:.1f}GB → device={actual_device}")
                except Exception:
                    actual_device = "cpu"   # torch 오류 시 CPU로 fallback

            print(f"[Embedding] BGE-M3 로딩 ({actual_device})")
            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=(actual_device == "cuda"),     # GPU면 fp16으로 메모리 절약, CPU면 False
                device=self.device,

            )
            print("[Embedding] BGE-M3 로딩 완료")

        return self._model


    def embed_text(self, text: str) -> list[float]:
        import time
        t0 = time.time()
        # 텍스트 1개 → 리스트로 감싸서 embed_texts에 넘기고 첫 번째 결과만 반환
        result = self.embed_texts([text])[0]
        print(f"[Embedding] embed_text 완료: {time.time()-t0:.2f}s (device={getattr(self._model, 'device', '?')})")
        return result


    def embed_texts(self, texts: list[str]) -> list[list[float]]:   #텍스트 여러 개 → 벡터 여러 개
        # 빈 리스트 들어오면 모델까지 안 가고 바로 반환
        if not texts:
            return []

        result = self.model.encode(
            texts,

            return_dense=True,          # 밀집 벡터 사용 (유사도 검색용)
            return_sparse=False,        # 키워드 벡터 미사용
            return_colbert_vecs=False,  # ColBERT 벡터 미사용

        )

        dense_vectors = result["dense_vecs"]    ## numpy 배열로 반환됨
        return [vector.tolist() for vector in dense_vectors]   # Qdrant에 넣으려면 Python 리스트여야 해서 .tolist()로 변환.