from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.Qdrant import qdrant_client
from app.core.config import settings


@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict


class QdrantVectorStore:
    """Qdrant collection operations for document chunks."""

    def __init__(self, collection_name: str | None = None) -> None:
        self.collection_name = collection_name or settings.QDRANT_COLLECTION

    def ensure_collection(self, vector_size: int) -> None:
        existing = [
            collection.name
            for collection in qdrant_client.get_collections().collections
        ]

        if self.collection_name not in existing:
            qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
            return

        collection_info = qdrant_client.get_collection(
            collection_name=self.collection_name
        )
        vectors_config = collection_info.config.params.vectors
        existing_vector_size = getattr(vectors_config, "size", None)

        if existing_vector_size is not None and existing_vector_size != vector_size:
            raise ValueError(
                f"Qdrant 컬렉션 벡터 차원이 맞지 않습니다. "
                f"collection={self.collection_name}, "
                f"existing={existing_vector_size}, current={vector_size}"
            )

    def upsert_chunks(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        source: str,
        metadata: dict | None = None,
    ) -> None:
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks와 embeddings 개수가 다릅니다. "
                f"chunks={len(chunks)}, embeddings={len(embeddings)}"
            )

        if not embeddings:
            return

        self.ensure_collection(vector_size=len(embeddings[0]))
        base_metadata = metadata or {}

        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{source}:{index}")),
                vector=embedding,
                payload={
                    **base_metadata,
                    "source": source,
                    "chunk_index": index,
                    "text": chunk,
                },
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        qdrant_client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

    def search(
        self,
        query_embedding: list[float],
        limit: int | None = None,
        source: str | None = None,
    ) -> list[SearchResult]:
        query_filter = None

        if source:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=source),
                    )
                ]
            )

        response = qdrant_client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit or settings.RAG_TOP_K,
            with_payload=True,
        )

        results: list[SearchResult] = []

        for point in response.points:
            payload = point.payload or {}

            results.append(
                SearchResult(
                    text=str(payload.get("text", "")),
                    score=float(point.score),
                    metadata={
                        key: value
                        for key, value in payload.items()
                        if key != "text"
                    },
                )
            )

        return results