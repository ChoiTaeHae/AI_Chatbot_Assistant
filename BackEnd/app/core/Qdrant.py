from qdrant_client import AsyncQdrantClient

from app.core.config import settings

qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    return qdrant_client


async def init_qdrant():
    global qdrant_client
    qdrant_client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


async def close_qdrant():
    global qdrant_client
    if qdrant_client:
        await qdrant_client.close()
        qdrant_client = None
