from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval.qdrant_store import QdrantVectorStore, SearchResult


class Retriever:
    """Embed a question and retrieve relevant chunks from Qdrant."""

    def __init__(
        self,
        embedding: BaaiEmbedding | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.embedding = embedding or BaaiEmbedding()
        self.vector_store = vector_store or QdrantVectorStore()

    def search(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
    ) -> list[SearchResult]:
        question = question.strip()

        if not question:
            return []

        query_embedding = self.embedding.embed_text(question)

        return self.vector_store.search(
            query_embedding=query_embedding,
            limit=limit,
            source=source,
        )

    def search_context(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
    ) -> str:
        results = self.search(
            question=question,
            limit=limit,
            source=source,
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