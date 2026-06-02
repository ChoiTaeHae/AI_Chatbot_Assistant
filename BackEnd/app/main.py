from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.Qdrant import close_qdrant, init_qdrant
from app.api.chat import router as chat_router
from app.services.chat_service import chat_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시
    chat_service.load_model()   # LLM 모델 GPU 로드
    await init_qdrant()
    yield
    # 서버 종료 시
    await close_qdrant()


app = FastAPI(
    title="학교생활지원 AI",
    description="대학교 학생들의 학교생활을 도와주는 AI 챗봇 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(chat_router, prefix="/api", tags=["챗봇"])


@app.get("/health", tags=["상태확인"])
async def health():
    """서버 상태 확인"""
    return {"status": "ok"}
