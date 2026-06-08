# 백엔드 개발 환경 세팅 가이드

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
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
```

> CUDA 정상 인식 확인:
> ```powershell
> python -c "import torch; print(torch.cuda.is_available())"
> ```
> `True` 가 나와야 정상. `False` 시 torch 재설치 필요:
> ```powershell
> pip uninstall torch torchvision -y
> pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
> ```

## 5. .env 파일 생성
BackEnd 폴더에 `.env` 파일 생성 후 아래 내용 입력:
```
# PostgreSQL
DB_HOST=220.90.180.82
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=8939
DB_NAME=school_chatbot

# Qdrant Cloud
QDRANT_URL=https://f5e01fdf-1c4d-4737-a7c6-42c73d65c479.us-east-1-1.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=[API 키 별도 문의]

# LLM
MODEL_PATH=./llm/bllossom-8b
DEVICE=cuda

# Embedding
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cpu

# Frontend
FRONTEND_ORIGINS=http://localhost:5173

# 개발 모드 (True 시 LLM 로딩 스킵 - 빠른 테스트용)
DEV_MODE=false
```

## 6. 서버 실행
```powershell
python -m uvicorn app.main:app --reload
```

## 7. API 문서 확인
브라우저에서 http://localhost:8000/docs 접속

---

## LLM 테스트 시
- `.env` 에서 `DEV_MODE=false` 로 변경
- 모델 파일(llm/bllossom-8b)이 있어야 함
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
