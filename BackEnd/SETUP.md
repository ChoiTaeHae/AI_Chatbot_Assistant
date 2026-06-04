# 백엔드 개발 환경 세팅 가이드

## 필수 조건
- Python 3.11.x (3.12 이상 사용 금지)
- CUDA 지원 GPU (RTX 시리즈 권장)
- Git

## Python 3.11 설치
https://www.python.org/downloads/release/python-3119/
- Windows installer (64-bit) 다운로드 후 설치
- 설치 시 "Add Python to PATH" 체크

---

## 1. 프로젝트 클론
```
git clone [저장소 URL]
cd AI_Chatbot_Assistant/BackEnd
```

## 2. 가상환경 생성
```
C:\Users\[유저명]\AppData\Local\Programs\Python\Python311\python.exe -m venv venv
venv\Scripts\activate
```

## 3. PyTorch CUDA 설치 (GPU 사용)
```
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## 4. 나머지 패키지 설치
```
pip install -r requirements.in
pip install bitsandbytes
```

## 5. .env 파일 생성
BackEnd 폴더에 .env 파일 생성 후 아래 내용 입력:
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

# Frontend
FRONTEND_ORIGINS=http://localhost:5173

# 개발 모드 (LLM 로딩 스킵 - 빠른 테스트용)
DEV_MODE=true
```

## 6. 서버 실행
```
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 7. API 문서 확인
브라우저에서 http://localhost:8000/docs 접속

---

## LLM 테스트 시
- .env 에서 DEV_MODE=false 로 변경
- 모델 파일(llm/bllossom-8b)이 있어야 함
- 모델 로딩 1~2분 소요

## 주의사항
- Python 3.14 사용 금지 (PyTorch 미지원)
- bcrypt 반드시 4.0.1 버전 사용
- transformers 반드시 4.44.2 버전 사용
- accelerate 반드시 0.27.2 버전 사용