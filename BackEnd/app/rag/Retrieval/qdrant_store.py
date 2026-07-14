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
        # 하이브리드 토글에 따라 컬렉션 자동 선택 (병행 구축·즉시 롤백용)
        self.collection_name = collection_name or settings.active_collection

    def _exists(self) -> bool:
        """컬렉션이 실제로 존재하는지. (하이브리드 켰지만 아직 재인제스트 전이면 없음)
        컬렉션은 첫 upsert 때 생성되므로, 읽기 작업은 없을 때 404 대신 빈 결과를 돌려야 함."""
        try:
            return qdrant_client.collection_exists(self.collection_name)
        except Exception:
            return False

    def ensure_collection(self, vector_size: int) -> None:
        existing = [
            collection.name
            for collection in qdrant_client.get_collections().collections
        ]

        if self.collection_name not in existing:
            if settings.HYBRID_SEARCH:
                # named 벡터: dense + sparse (bge-m3 하이브리드)
                qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        "dense": VectorParams(size=vector_size, distance=Distance.COSINE),
                    },
                    sparse_vectors_config={
                        "sparse": models.SparseVectorParams(),
                    },
                )
            else:
                qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE,
                    ),
                )

        if not settings.HYBRID_SEARCH:
            # dense-only 컬렉션만 차원 검증 (하이브리드는 named 벡터라 구조가 다름)
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

        # source 인덱스 — delete_by_source / source 필터 검색에 필수
        qdrant_client.create_payload_index(
            collection_name=self.collection_name,
            field_name="source",
            field_schema=models.PayloadSchemaType.KEYWORD,
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
        sparse_vectors: list[tuple[list[int], list[float]]] | None = None,  # 하이브리드용 키워드 벡터
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
        hybrid = settings.HYBRID_SEARCH and sparse_vectors is not None

        def _vector(index: int, embedding: list[float]):
            if not hybrid:
                return embedding
            named = {"dense": embedding}
            idx, val = sparse_vectors[index]
            if idx:   # 빈 sparse(불용어뿐 등)면 sparse 키 생략 → dense만 저장
                named["sparse"] = models.SparseVector(indices=idx, values=val)
            return named

        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{source}:{index}")),
                vector=_vector(index, embedding),
                payload={
                    "chunk_index": index,
                    "source": source,
                    **base_metadata,
                    "topic": topic,
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
        sparse_query: tuple[list[int], list[float]] | None = None,  # 하이브리드용 키워드 쿼리
    ) -> list[SearchResult]:
        if not self._exists():
            return []   # 컬렉션 미생성(재인제스트 전) → 빈 결과

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

        lim = limit or settings.RAG_TOP_K

        if settings.HYBRID_SEARCH:
            has_sparse = bool(sparse_query and sparse_query[0])
            if has_sparse:
                # dense + sparse 두 갈래 prefetch → RRF 융합. 필터는 양쪽 모두에 적용.
                prefetch_limit = max(lim, 40)   # 후보 넉넉히 (sparse 노이즈에 슬롯 안 뺏기게)
                s_idx, s_val = sparse_query
                response = qdrant_client.query_points(
                    collection_name=self.collection_name,
                    prefetch=[
                        models.Prefetch(
                            query=query_embedding, using="dense",
                            limit=prefetch_limit, filter=query_filter,
                        ),
                        models.Prefetch(
                            query=models.SparseVector(indices=s_idx, values=s_val),
                            using="sparse", limit=prefetch_limit, filter=query_filter,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=lim,
                    with_payload=True,
                )
            else:
                # 빈 sparse → dense 단독 폴백 (named 벡터라 using 지정)
                response = qdrant_client.query_points(
                    collection_name=self.collection_name,
                    query=query_embedding, using="dense",
                    query_filter=query_filter,
                    limit=lim,
                    with_payload=True,
                )
        else:
            # 기존 dense-only (unnamed 벡터) — 동작 불변
            response = qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=lim,
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

    def _ensure_source_index(self) -> None:
        """source payload 인덱스 보장 (구 컬렉션·인덱스 누락 자가치유). 이미 있으면 무시."""
        try:
            qdrant_client.create_payload_index(
                collection_name=self.collection_name,
                field_name="source",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

    def delete_by_source(self, source: str) -> int:
        """source 기준으로 문서 청크 전체 삭제. 삭제된 포인트 수 반환."""
        if not self._exists():
            return 0
        self._ensure_source_index()   # source 필터 전에 인덱스 보장
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

    def count_by_topic(self, topic: str) -> int:
        """topic에 등록된 RAG 청크 수 반환."""
        if not self._exists():
            return 0
        result = qdrant_client.count(
            collection_name=self.collection_name,
            count_filter=Filter(
                must=[FieldCondition(key="topic", match=MatchValue(value=topic))]
            ),
            exact=True,
        )
        return result.count

    def list_sources(self) -> list[dict]:
        """저장된 문서 source 목록 반환."""
        if not self._exists():
            return []
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