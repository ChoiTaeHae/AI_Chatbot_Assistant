"""설치 시 필요한 모델을 컨테이너 안에서 내려받는다.

호스트에서 받지 않고 컨테이너에서 받는 이유
    ./BackEnd/llm 과 ./models 는 바인드 마운트라 컨테이너가 받으면 호스트에
    그대로 떨어진다. 덕분에 수령자 PC에 Git LFS 를 설치할 필요가 없다.
    (리랭커는 LFS 저장소라 git clone 하려면 LFS 가 필요했다)

이미 있으면 건너뛴다. 중간에 끊겨도 다시 실행하면 이어받는다.

실행:
    docker compose -f deploy/docker-compose.yml run --rm --no-deps backend \
        python3 -m scripts.download_models
"""
import os
import sys

LLM_REPO = "MLP-KTLim/llama-3-Korean-Bllossom-8B-gguf-Q4_K_M"
LLM_FILE = "llama-3-Korean-Bllossom-8B-Q4_K_M.gguf"
LLM_DIR = "/app/llm"

RERANK_REPO = "dragonkue/bge-reranker-v2-m3-ko"
RERANK_DIR = "/app/models/bge-reranker-v2-m3-ko"

# 리랭커는 학습용 노트북·중복 포맷까지 들어 있어 필요한 것만 받는다.
RERANK_ALLOW = ["*.json", "*.safetensors", "*.model", "*.txt"]


def human(n: int) -> str:
    return f"{n / 1024 / 1024 / 1024:.2f} GB" if n > 1 << 30 else f"{n / 1024 / 1024:.0f} MB"


def main() -> int:
    from huggingface_hub import hf_hub_download, snapshot_download

    print("=" * 60)
    print("1/2  답변 생성 모델 (약 4.9 GB)")
    print("=" * 60)
    target = os.path.join(LLM_DIR, LLM_FILE)
    if os.path.exists(target) and os.path.getsize(target) > 4 * (1 << 30):
        print(f"  이미 있음 ({human(os.path.getsize(target))}) — 건너뜀")
    else:
        os.makedirs(LLM_DIR, exist_ok=True)
        hf_hub_download(repo_id=LLM_REPO, filename=LLM_FILE,
                        local_dir=LLM_DIR)
        print(f"  완료 — {human(os.path.getsize(target))}")

    print()
    print("=" * 60)
    print("2/2  리랭커 모델 (약 2.2 GB)")
    print("=" * 60)
    weight = os.path.join(RERANK_DIR, "model.safetensors")
    if os.path.exists(weight) and os.path.getsize(weight) > (1 << 30):
        print(f"  이미 있음 ({human(os.path.getsize(weight))}) — 건너뜀")
    else:
        os.makedirs(RERANK_DIR, exist_ok=True)
        snapshot_download(repo_id=RERANK_REPO, local_dir=RERANK_DIR,
                          allow_patterns=RERANK_ALLOW)
        print(f"  완료 — {human(os.path.getsize(weight))}")

    print()
    print("임베딩 모델(BGE-M3, 약 2.3 GB)은 서버 최초 기동 시 자동으로 받는다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n중단됨. 다시 실행하면 이어받는다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[실패] {type(e).__name__}: {e}")
        print("네트워크를 확인하고 다시 실행하세요. 받은 부분은 유지됩니다.")
        sys.exit(1)
