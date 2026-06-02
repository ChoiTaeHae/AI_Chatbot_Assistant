# from contextlib import asynccontextmanager

# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from app.core.Qdrant import close_qdrant, init_qdrant
# from app.api.auth import router as chat_router


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     await init_qdrant()
#     yield
#     await close_qdrant()


# app = FastAPI(title="학교생활지원 AI", version="0.1.0", lifespan=lifespan)

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(chat_router, prefix="/api")


# @app.get("/health")
# async def health():
#     return {"status": "ok"}

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = (
    "postgresql://postgres:8939@220.90.180.82:5432/school_chatbot"
)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)