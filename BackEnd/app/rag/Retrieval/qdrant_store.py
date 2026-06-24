from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5
from qdrant_client import models

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
    FilterSelector,
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
        
        qdrant_client.create_payload_index(
            collection_name=self.collection_name,
            field_name="file_name",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        
        # topic도 나중을 위해 만듦
        qdrant_client.create_payload_index(
            collection_name=self.collection_name,
            field_name="topic",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        qdrant_client.create_payload_index(
            collection_name=self.collection_name,
            field_name="doc_date",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    def upsert_chunks(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        source: str,
        metadata: dict | None = None,
        topic: str | None = None,
        chunk_metas: list[dict] | None = None,  # chapter, article, path 메타데이터
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
                    "topic": topic,
                    "chunk_index": index,
                    "text": chunk,
                    # chapter, article, path 저장 (없으면 None)
                    **(chunk_metas[index] if chunk_metas else {}),
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
        topic: str | None = None,
    ) -> list[SearchResult]:
        query_filter = None

        if topic:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="topic",
                        match=MatchValue(value=topic),
                    )
                ]
            )
        elif source:
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

    def delete_by_source(self, source: str) -> int:
        """source 기준으로 문서 청크 전체 삭제. 삭제된 포인트 수 반환."""
        count_result = qdrant_client.count(
            collection_name=self.collection_name,
            count_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
            exact=True,
        )
        count = count_result.count

        qdrant_client.delete(
            collection_name=self.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                )
            ),
        )
        return count

    def list_sources(self) -> list[dict]:
        """저장된 문서 source 목록 반환."""
        result = qdrant_client.scroll(
            collection_name=self.collection_name,
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
        seen = {}
        for point in result[0]:
            payload = point.payload or {}
            source = payload.get("source", "unknown")
            if source not in seen:
                seen[source] = {
                    "source": source,
                    "file_name": payload.get("file_name", ""),
                    "topic": payload.get("topic", ""),
                    "doc_date": payload.get("doc_date"), 
                    "chunks": 1,
                }
            else:
                seen[source]["chunks"] += 1
        return list(seen.values())