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
    # 답변 생성 백엔드: "local"(로컬 Bllossom GGUF) | "vertex"(Vertex AI Gemini)
    LLM_PROVIDER: str = "local"
    MODEL_PATH: str = "./llm/bllossom-8b-Q8_0.gguf"
    DEVICE: str = "cuda"

    # Gemini — LLM_PROVIDER=vertex 일 때 사용.
    # 인증: GEMINI_API_KEY 있으면 API 키 방식(Gemini Developer API),
    #       없으면 서비스계정(Vertex AI)로 폴백.
    GEMINI_API_KEY: str = ""          # API 키 (.env에만, 커밋 금지)
    GEMINI_MODEL: str = "gemini-2.0-flash-001"
    # 아래는 서비스계정(Vertex) 방식일 때만 필요
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "us-central1"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cuda"

    # RAG
    QDRANT_COLLECTION: str = "school_documents"
    RAG_TOP_K: int = 3

    # URL 크롤 문서 청크 최대 크기(자). 상한일 뿐 — 작은 섹션은 자연 크기로 저장됨.
    # 1500: 한 섹션(예: 수료증명서 기준 전체)을 한 덩어리로 유지 → '전체' 질문에 유리.
    # 낮추면 더 잘게(콕집는 질문 정밀↑, 800 미만은 파편). 업로드/졸업 표 경로는 무관.
    CRAWL_CHUNK_SIZE: int = 1500

    # 하이브리드 검색 (dense + sparse, bge-m3). True 시 별도 컬렉션(HYBRID_COLLECTION) 사용.
    # 롤백은 이 토글만 False로 → dense-only 기존 컬렉션으로 즉시 복귀.
    HYBRID_SEARCH: bool = False
    HYBRID_COLLECTION: str = "school_documents_hybrid"

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

    @property
    def active_collection(self) -> str:
        """현재 사용할 Qdrant 컬렉션명. 하이브리드면 별도 컬렉션."""
        return self.HYBRID_COLLECTION if self.HYBRID_SEARCH else self.QDRANT_COLLECTION


settings = Settings()
