from pathlib import Path

from app.rag.Chunking import split_by_article
from app.rag.Embedding import BaaiEmbedding
from app.rag.Loader import DoclingLoader
from app.rag.Retrieval import QdrantVectorStore, Retriever, SearchResult


class RagService:
    """Application service that composes Docling, BAAI embedding, and Qdrant."""

    def __init__(self) -> None:
        self._loader: DoclingLoader | None = None
        self._embedding: BaaiEmbedding | None = None
        self._vector_store: QdrantVectorStore | None = None
        self._retriever: Retriever | None = None

    @property
    def loader(self) -> DoclingLoader:
        if self._loader is None:
            self._loader = DoclingLoader()
        return self._loader

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = BaaiEmbedding()
        return self._embedding

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self._vector_store = QdrantVectorStore()
        return self._vector_store

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever(
                embedding=self.embedding,
                vector_store=self.vector_store,
            )
        return self._retriever

    def ingest_document(self, file_path: str | Path, source: str | None = None) -> int:
        path = Path(file_path)
        source_name = source or path.stem
        text = self.loader.load_text(path)
        chunks = split_by_article(text)
        if not chunks:
            return 0

        embeddings = self.embedding.embed_texts(chunks)
        self.vector_store.upsert_chunks(
            chunks=chunks,
            embeddings=embeddings,
            source=source_name,
            metadata={"file_name": path.name},
        )
        return len(chunks)

    def search(self, question: str, limit: int | None = None, source: str | None = None) -> list[SearchResult]:
        return self.retriever.search(question=question, limit=limit, source=source)

    def search_context(self, question: str, limit: int | None = None, source: str | None = None) -> str:
        return self.retriever.search_context(question=question, limit=limit, source=source)


rag_service = RagService()
