from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval.qdrant_store import (
    QdrantVectorStore,
    SearchResult,
)
from app.rag.Retrieval.Reranker import BgeReranker


class Retriever:
    """Embed a question and retrieve relevant chunks from Qdrant."""

    def __init__(
        self,
        embedding: BaaiEmbedding | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.embedding = embedding or BaaiEmbedding()
        self.vector_store = vector_store or QdrantVectorStore()
        self.reranker = BgeReranker()

    def search(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
        topic: str | None = None,
    ) -> list[SearchResult]:

        question = question.strip()

        if not question:
            return []

        query_embedding = self.embedding.embed_text(question)

        # Dense 검색 Top10
        results = self.vector_store.search(
            query_embedding=query_embedding,
            limit=10,
            source=source,
            topic=topic,
        )

        if not results:
            return []

        scores = self.reranker.rerank(
            question,
            [result.text for result in results],
        )

        reranked = sorted(
            zip(results, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        top_k = limit or 3

        final_results = [
            result
            for result, _ in reranked[:top_k]
        ]

        print(f"[Retriever] 최종 반환 ({len(final_results)}개)")

        return final_results

    def search_context(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
        topic: str | None = None,
    ) -> str:

        results = self.search(
            question=question,
            limit=limit,
            source=source,
            topic=topic,
        )

        return "\n\n".join(
            f"[source={self._format_source(result)}, score={result.score:.3f}]\n{result.text}"
            for result in results
            if result.text
        )

    def _format_source(self, result: SearchResult) -> str:
        return (
            result.metadata.get("source")
            or result.metadata.get("file_name")
            or "unknown"
        )