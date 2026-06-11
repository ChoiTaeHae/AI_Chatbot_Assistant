from pathlib import Path

from app.rag.Chunking import split_by_article
from app.rag.Embedding import BaaiEmbedding
from app.rag.Loader import DoclingLoader
from app.rag.Loader.fast_loader import FastLoader
from app.rag.Retrieval import QdrantVectorStore, Retriever, SearchResult


class RagService:
    """Application service that composes FastLoader/Docling, BAAI embedding, and Qdrant."""

    def __init__(self) -> None:
        self._fast_loader: FastLoader | None = None
        self._docling_loader: DoclingLoader | None = None
        self._embedding: BaaiEmbedding | None = None
        self._vector_store: QdrantVectorStore | None = None
        self._retriever: Retriever | None = None

    @property
    def fast_loader(self) -> FastLoader:
        if self._fast_loader is None:
            self._fast_loader = FastLoader()
        return self._fast_loader

    @property
    def loader(self) -> DoclingLoader:
        """하위 호환용 - Docling 로더"""
        if self._docling_loader is None:
            self._docling_loader = DoclingLoader()
        return self._docling_loader

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

    def ingest_document(self, file_path: str | Path, source: str | None = None, topic: str | None = None) -> int:
        path = Path(file_path)
        source_name = source or path.stem

        # FastLoader로 빠르게 시도, 실패 시 Docling으로 폴백
        text = None
        try:
            print(f"[RAG] FastLoader로 텍스트 추출 시도: {path.name}")
            text = self.fast_loader.load_text(path)
            print(f"[RAG] FastLoader 성공: {len(text)}자")
        except Exception as e:
            print(f"[RAG] FastLoader 실패 ({e}), Docling으로 재시도...")
            try:
                text = self.loader.load_text(path)
                print(f"[RAG] Docling 성공: {len(text)}자")
            except Exception as e2:
                raise RuntimeError(f"텍스트 추출 실패: {e2}")

        if not text or not text.strip():
            return 0

        chunks = split_by_article(text)
        print(f"[RAG] chunk 개수: {len(chunks)}")

        if not chunks:
            print("[RAG] chunk 생성 실패")
            return 0
        
        print("[RAG] embedding 시작")
        embeddings = self.embedding.embed_texts(chunks)
        print("[RAG] embedding 완료")

        print("[RAG] qdrant 저장 시작")
        self.vector_store.upsert_chunks(
            chunks=chunks,
            embeddings=embeddings,
            source=source_name,
            metadata={"file_name": path.name},
            topic=topic,
        )
        print("[RAG] qdrant 저장 완료")
        return len(chunks)

    def search(self, question: str, limit: int | None = None, source: str | None = None, topic: str | None = None) -> list[SearchResult]:
        return self.retriever.search(question=question, limit=limit, source=source, topic=topic)

    def search_context(self, question: str, limit: int | None = None, source: str | None = None, topic: str | None = None) -> str:
        return self.retriever.search_context(question=question, limit=limit, source=source, topic=topic)


rag_service = RagService()
