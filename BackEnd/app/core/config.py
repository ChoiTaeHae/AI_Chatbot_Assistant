from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    # Qdrant Cloud
    QDRANT_URL: str
    QDRANT_API_KEY: str

    # Kakao Map
    KAKAO_API_KEY: str = ""

    # LLM
    MODEL_PATH: str = "./llm/bllossom-8b-Q8_0.gguf"
    DEVICE: str = "cuda"

    # LLM Provider 스위치: "local"(llama-cpp 자체 호스팅) | "gemini"(Google API)
    LLM_PROVIDER: str = "local"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cuda"

    # RAG
    QDRANT_COLLECTION: str = "school_documents"
    RAG_TOP_K: int = 3

    # Frontend
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    # JWT — .env 에 반드시 설정 (미설정 시 서버 기동 실패)
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24   # 24시간

    # Reranker 모델 경로 (venv: 절대경로, Docker: /app/models/ko-reranker)
    RERANKER_MODEL_PATH: str = "/app/models/ko-reranker"
    # 리랭커 실행 device: "cuda"(GPU, 빠름) | "cpu"(느림, VRAM 부족 시)
    # 8B LLM과 함께 GPU에 올려 OOM나면 cpu로.
    RERANKER_DEVICE: str = "cuda"

    # 개발 모드 (True 시 LLM 로딩 스킵)
    DEV_MODE: bool = False

    # Rate Limiting (False 시 제한 없음 — 개발 환경에서 비활성화)
    RATE_LIMIT_ENABLED: bool = True
    CHAT_RATE_LIMIT: int = 20       # 분당 최대 요청 수
    RATE_LIMIT_WINDOW: int = 60     # 윈도우 크기 (초)


settings = Settings()
