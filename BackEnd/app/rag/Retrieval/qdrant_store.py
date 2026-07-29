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
        """저장된 문서 source 목록 반환.

        url·contact_name·contact_phone도 함께 반환한다 — 관리자 페이지의 '문서 수정'
        폼에 기존값을 채우려면 목록만으로 충분해야 하기 때문(문서별 상세 조회 왕복 불필요).
        같은 source의 청크는 값이 동일하므로 첫 청크 기준으로 담는다.
        """
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
                    "url": payload.get("url"),
                    "contact_name": payload.get("contact_name"),
                    "contact_phone": payload.get("contact_phone"),
                    "chunks": 1,
                }
            else:
                seen[source]["chunks"] += 1
        return list(seen.values())

    def list_chunks(self, source: str) -> list[dict]:
        """문서 하나의 청크 전체를 chunk_index 순으로 반환 (본문 포함, 벡터 제외).

        '문서가 실제로 어떻게 쪼개져 저장됐는지'를 관리자 화면에서 보기 위한 조회 경로다.
        벡터는 1024차원이라 화면에 쓸 일이 없으면서 응답만 무겁게 하므로 가져오지 않는다.
        """
        if not self._exists():
            return []
        self._ensure_source_index()
        points, _ = qdrant_client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
            limit=1000,      # 문서 하나가 이보다 잘게 쪼개질 일은 없다(전체 컬렉션이 약 1천 청크)
            with_payload=True,
            with_vectors=False,
        )
        chunks = [
            {
                "point_id": str(point.id),
                "chunk_index": (point.payload or {}).get("chunk_index", 0),
                "text": str((point.payload or {}).get("text", "")),
                "path": (point.payload or {}).get("path") or None,
                "chapter": (point.payload or {}).get("chapter") or None,
                "article": (point.payload or {}).get("article") or None,
            }
            for point in points
        ]
        # scroll은 저장 순서를 보장하지 않는다 — 화면 번호와 실제 순서를 맞추려면 정렬이 필요
        chunks.sort(key=lambda c: c["chunk_index"])
        return chunks

    def get_chunk(self, source: str, chunk_index: int) -> dict | None:
        """청크 1개 조회. 수정 전에 원본 payload(특히 임베딩 규칙에 쓰이는 path)를 읽는 용도."""
        for chunk in self.list_chunks(source):
            if chunk["chunk_index"] == chunk_index:
                return chunk
        return None

    def update_chunk_text(
        self,
        point_id: str,
        text: str,
        embedding: list[float],
        sparse_vector: tuple[list[int], list[float]] | None = None,
    ) -> None:
        """청크 1개의 본문과 벡터를 함께 교체한다.

        본문만 바꾸고 벡터를 두면 화면에 보이는 글과 검색에 쓰이는 벡터가 어긋나
        추적하기 어려운 검색 오류가 된다. 그래서 이 경로는 둘을 항상 같이 갱신한다.
        upsert로 포인트를 통째로 덮어쓰지 않고 update_vectors + set_payload로 나눈 이유는,
        topic·doc_date·chunk_index 등 나머지 payload를 다시 조립하다 흘리는 일을 막기 위함이다.
        """
        if settings.HYBRID_SEARCH:
            vector: dict | list[float] = {"dense": embedding}
            if sparse_vector and sparse_vector[0]:
                indices, values = sparse_vector
                vector["sparse"] = models.SparseVector(indices=indices, values=values)
            # 빈 sparse(불용어뿐)는 인제스트와 동일하게 키를 생략한다 → 검색 시 dense 폴백
        else:
            vector = embedding

        qdrant_client.update_vectors(
            collection_name=self.collection_name,
            points=[models.PointVectors(id=point_id, vector=vector)],
        )
        qdrant_client.set_payload(
            collection_name=self.collection_name,
            payload={"text": text},
            points=[point_id],
        )

    # 문서 수정으로 갱신할 수 있는 payload 필드 — 화이트리스트로 고정한다.
    # text/chunk_index/source 등 검색 구조에 관여하는 키는 여기에 넣지 않는다
    # (source는 point id를 결정하므로 payload만 바꾸면 데이터가 어긋난다).
    EDITABLE_META_FIELDS = ("topic", "doc_date", "url", "contact_name", "contact_phone")

    def update_source_metadata(self, source: str, fields: dict) -> int:
        """source에 속한 모든 청크의 메타데이터를 일괄 갱신하고 갱신된 청크 수를 반환.

        set_payload는 지정한 키만 덮어쓰므로 **본문(text)과 벡터는 그대로 유지**된다.
        기존에는 메타 하나를 고치려 해도 '삭제 후 재업로드'뿐이라, 재청킹·재임베딩이
        일어나면서 손으로 정리해 둔 청크 본문까지 함께 날아갔다. 이 경로는 그 위험이 없다.
        """
        if not self._exists():
            return 0
        self._ensure_source_index()
        payload = {k: v for k, v in fields.items() if k in self.EDITABLE_META_FIELDS}
        if not payload:
            return 0

        source_filter = Filter(
            must=[FieldCondition(key="source", match=MatchValue(value=source))]
        )
        count = qdrant_client.count(
            collection_name=self.collection_name,
            count_filter=source_filter,
            exact=True,
        ).count
        if count == 0:
            return 0

        # None은 '값 비우기' 의도이므로 set_payload가 아니라 delete_payload로 처리한다
        # (set_payload에 None을 주면 null이 그대로 박혀 필드 유무 판정이 흔들린다).
        to_set = {k: v for k, v in payload.items() if v is not None}
        to_clear = [k for k, v in payload.items() if v is None]
        if to_set:
            qdrant_client.set_payload(
                collection_name=self.collection_name,
                payload=to_set,
                points=FilterSelector(filter=source_filter).filter,
            )
        if to_clear:
            qdrant_client.delete_payload(
                collection_name=self.collection_name,
                keys=to_clear,
                points=FilterSelector(filter=source_filter).filter,
            )
        return count