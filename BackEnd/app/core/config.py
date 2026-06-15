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

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cuda"

    # RAG
    QDRANT_COLLECTION: str = "school_documents"
    RAG_TOP_K: int = 3

    # Frontend
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    # JWT
    SECRET_KEY: str = "changeme-set-strong-key-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24   # 24시간

    # 개발 모드 (True 시 LLM 로딩 스킵)
    DEV_MODE: bool = False


settings = Settings()
