from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/school_ai"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "school_docs"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # LLM 모델 경로 (로컬 safetensors)
    MODEL_PATH: str = r"D:\202210887\학교생활지원AI\AI_Chatbot_Assistant\BackEnd\llm\bllossom-8b"


settings = Settings()
