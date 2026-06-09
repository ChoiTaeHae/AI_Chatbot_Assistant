# app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.DB_USER}:"
    f"{settings.DB_PASSWORD}@"
    f"{settings.DB_HOST}:"
    f"{settings.DB_PORT}/"
    f"{settings.DB_NAME}"
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

AsyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False   # commit 후 속성 만료 방지 (async 환경 필수)
)

Base = declarative_base()

# 동기 세션 (schedule_service 등 동기 코드 호환용)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker as sync_sessionmaker

SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{settings.DB_USER}:"
    f"{settings.DB_PASSWORD}@"
    f"{settings.DB_HOST}:"
    f"{settings.DB_PORT}/"
    f"{settings.DB_NAME}"
)
sync_engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sync_sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


async def get_db():
    async with AsyncSessionLocal() as db :
        try:
            yield db
        finally:
            await db.close()