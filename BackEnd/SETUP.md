# 백엔드 개발 환경 세팅 가이드

> **이 문서는 venv로 백엔드만 직접 실행하는 방법입니다.**
> 평소 개발·시연은 Docker로 하며, 그쪽은 아래를 참고하세요.
>
> | 목적 | 문서 | 실행 |
> |---|---|---|
> | 평소 개발 (공용 DB 접속) | — | `docker compose up -d` |
> | 배포·독립 실행 | `deploy/설치_방법.md` | `docker compose -f deploy/docker-compose.yml up -d` |
> | 백엔드만 디버깅 | **이 문서** | `python -m uvicorn app.main:app --reload` |
>
> Docker를 쓰면 아래 2~4번(가상환경·패키지·PyTorch)이 전부 불필요합니다.
> 프론트엔드까지 함께 뜨고, llama-cpp CUDA 빌드도 이미지 안에서 끝납니다.

## 필수 조건
- Python 3.11.x (3.12 이상 사용 금지)
- CUDA 지원 GPU (RTX 시리즈 권장)
- Git

## Python 3.11 설치
https://www.python.org/downloads/release/python-3119/
- Windows installer (64-bit) 다운로드 후 설치
- 설치 시 **"Add Python to PATH"** 반드시 체크
- 설치 후 터미널 새로 열기

---

## 1. 프로젝트 클론
```powershell
git clone [저장소 URL]
cd AI_Chatbot_Assistant/BackEnd
```

## 2. 가상환경 생성 및 활성화
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> PowerShell 스크립트 실행 오류 시 먼저 실행:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

## 3. 일반 패키지 설치
```powershell
pip install -r requirements_lock.txt
```

## 4. PyTorch CUDA 버전 별도 설치 (GPU 사용)
```powershell
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
```

> CUDA 정상 인식 확인:
> ```powershell
> python -c "import torch; print(torch.cuda.is_available())"
> ```
> `True` 가 나와야 정상. `False` 시 torch 재설치 필요:
> ```powershell
> pip uninstall torch torchvision -y
> pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
> ```

## 5. .env 파일 생성

> **접속 정보는 이 문서에 적지 않는다.**
> 이 파일은 git으로 공유되므로 비밀번호·API 키를 넣으면 저장소에 그대로 남는다.
> 아래 `[별도 안내]` 값은 팀 내부에서 따로 전달받는다.

BackEnd 폴더에 `.env` 파일 생성 후 아래 내용 입력:
```
# PostgreSQL
DB_HOST=[별도 안내]
DB_PORT=5432
DB_USER=[별도 안내]
DB_PASSWORD=[별도 안내]
DB_NAME=school_chatbot

# Qdrant Cloud
QDRANT_URL=[별도 안내]
QDRANT_API_KEY=[별도 안내]

# 인증 (아무 긴 문자열. python -c "import secrets; print(secrets.token_urlsafe(48))")
SECRET_KEY=[각자 생성]

# 답변 생성 LLM
#   local  = llm 폴더의 GGUF를 직접 구동 (llama-cpp-python 필요)
#   vertex = Gemini. gcp-sa.json 서비스계정 키가 있어야 한다.
LLM_PROVIDER=local
MODEL_PATH=./llm/llama-3-Korean-Bllossom-8B-Q4_K_M.gguf
DEVICE=cuda
LLM_GPU_LAYERS=25      # 3070(8GB) 기준. VRAM 크면 -1(전체)
LLM_N_CTX=4096

# 임베딩 (첫 실행 시 HuggingFace에서 자동 다운로드, 약 2.3GB)
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_PROVIDER=local
EMBEDDING_DEVICE=cuda

# 리랭커 — 모델 폴더를 미리 받아둬야 한다 (아래 6번)
RERANKER_MODEL_PATH=../models/bge-reranker-v2-m3-ko
RERANKER_DEVICE=cuda

# 하이브리드 검색 (dense + sparse). true 면 school_documents_hybrid 컬렉션 사용
HYBRID_SEARCH=true

# Frontend
FRONTEND_ORIGINS=http://localhost:5173

# 개발 모드 (true 시 LLM 로딩 스킵 - 빠른 테스트용)
DEV_MODE=false

# 선택 기능 — 없으면 해당 기능만 동작하지 않는다
OPENWEATHER_API_KEY=      # 날씨 카드
KAKAO_API_KEY=            # 캠퍼스 길안내
```

> Docker 실행 시에는 `DB_HOST`, `QDRANT_URL`, `RERANKER_MODEL_PATH` 값이 달라집니다.
> `deploy/.env.example` 을 참고하세요.

## 6. 리랭커 모델 다운로드 (2.2GB)

검색 결과 재정렬에 사용합니다. 없으면 서버 기동이 실패합니다.

```powershell
cd AI_Chatbot_Assistant\models
git lfs install
git clone https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko
```

## 7. 답변 생성 모델 다운로드 (4.9GB)

`LLM_PROVIDER=local` 로 쓸 때만 필요합니다. (`vertex` 면 건너뜁니다)

https://huggingface.co/MLP-KTLim/llama-3-Korean-Bllossom-8B-gguf-Q4_K_M
에서 `llama-3-Korean-Bllossom-8B-Q4_K_M.gguf` 를 받아 `BackEnd/llm/` 에 넣습니다.

## 8. 서버 실행
```powershell
python -m uvicorn app.main:app --reload
```

## 9. API 문서 확인
브라우저에서 http://localhost:8000/docs 접속

---

## LLM 테스트 시
- `.env` 에서 `DEV_MODE=false` 로 변경
- 모델 파일(`llm/llama-3-Korean-Bllossom-8B-Q4_K_M.gguf`)이 있어야 함
- 모델 로딩 1~2분 소요

## 개발/테스트 모드 (LLM 없이 실행)
- `.env` 에서 `DEV_MODE=true` 로 변경
- 로그인, DB 기능은 정상 동작
- AI 채팅 응답은 비활성화

## 주의사항
- Python 3.12 이상 사용 금지 (PyTorch 미지원)
- torch는 반드시 4번 단계처럼 CUDA 인덱스에서 별도 설치
- requirements_lock.txt 의 torch 관련 줄은 주석 처리되어 있으므로 3번 단계에서 자동 스킵됨
- accelerate 반드시 0.27.2 버전 사용 (변경 금지)
- bcrypt 반드시 4.0.1 버전 사용 (변경 금지)
- transformers 반드시 4.44.2 버전 사용 (변경 금지)
