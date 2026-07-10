from pathlib import Path

from app.rag.Chunking import smart_split
from app.rag.Embedding import BaaiEmbedding
from app.rag.Loader import DoclingLoader
from app.rag.Loader.fast_loader import FastLoader
from app.rag.Retrieval import QdrantVectorStore, Retriever, SearchResult
from app.rag.Preprocessing import preprocess_text


class RagService:
    """Application service that composes FastLoader/Docling/OCR, BAAI embedding, and Qdrant."""

    def __init__(self) -> None:
        self._fast_loader: FastLoader | None = None
        self._docling_loader: DoclingLoader | None = None
        self._embedding: BaaiEmbedding | None = None
        self._vector_store: QdrantVectorStore | None = None
        self._retriever: Retriever | None = None
        self._ocr_processor = None      # OcrProcessor (지연 로딩)

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

    @property
    def ocr_processor(self):
        """스캔 PDF / 이미지 OCR 처리기 (지연 로딩)"""
        if self._ocr_processor is None:
            from app.rag.Loader.ocr_processor import OcrProcessor
            self._ocr_processor = OcrProcessor()
        return self._ocr_processor

    # 이미지 확장자 목록 — FastLoader/Docling 은 이미지 미지원 → OCR 직행
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

    def ingest_document(self, file_path: str | Path, source: str | None = None, topic: str | None = None, doc_date: str | None = None, url: str | None = None, contact_name: str | None = None, contact_phone: str | None = None, original_filename: str | None = None) -> int:
        path = Path(file_path)
        source_name = source or path.stem
        suffix = path.suffix.lower()

        text = None

        # 이미지 파일 → FastLoader/Docling 없이 OCR 직행
        if suffix in self._IMAGE_EXTS:
            print(f"[RAG] 이미지 파일 감지 → OCR 직접 처리: {path.name}")
            try:
                text = self.ocr_processor.process_image(path)
                print(f"[RAG] 이미지 OCR 성공: {len(text)}자")
            except Exception as e:
                raise RuntimeError(f"이미지 OCR 실패: {e}")
        else:
            # FastLoader → Docling → OCR 순서로 폴백
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
                    print(f"[RAG] Docling 실패 ({e2}), OCR로 재시도...")
                    try:
                        text = self.ocr_processor.load_text_with_ocr(path)
                        print(f"[RAG] OCR 성공: {len(text)}자")
                    except Exception as e3:
                        raise RuntimeError(f"텍스트 추출 실패 (FastLoader/Docling/OCR 전부 실패): {e3}")

        if not text or not text.strip():
            return 0

        # 텍스트 정제
        text = preprocess_text(text)

        # 1. 텍스트 분할 (메타데이터 포함)
        # smart_split은 list[dict] 반환
        # {"chunk_id", "chapter", "article", "path", "text", "embedding_text"}
        chunk_dicts = smart_split(text, embed_fn=self.embedding.embed_texts)
        if not chunk_dicts:
            print("[RAG] chunk 생성 실패")
            return 0

        # 2. 임베딩 모델용 순수 텍스트와 DB 저장용 텍스트 분리
        embedding_texts = [c["embedding_text"] for c in chunk_dicts]
        # Qdrant 저장용 원본 텍스트
        chunk_texts = [c["text"] for c in chunk_dicts]

        # 3. 임베딩(벡터 변환) 실행
        print(f"[RAG] embedding 시작 ({len(chunk_dicts)}개 청크)")
        embeddings = self.embedding.embed_texts(embedding_texts)
        print("[RAG] embedding 완료")

        # 4. 같은 source의 기존 청크 제거 (재인제스트 멱등성 보장)
        # - upsert는 인덱스 단위 덮어쓰기라, 새 청크 수가 줄면 옛 상위 인덱스가 잔존함
        # - 새 청크가 준비된 이후 시점에 삭제해 추출/청킹 실패 시 데이터 손실 방지
        deleted = self.vector_store.delete_by_source(source_name)
        if deleted:
            print(f"[RAG] 기존 청크 {deleted}개 삭제 후 재인제스트: {source_name}")

        # 5. Qdrant 벡터 DB에 저장
        print("[RAG] qdrant 저장 시작")
        self.vector_store.upsert_chunks(
            chunks=chunk_texts,
            embeddings=embeddings,
            source=source_name,
            metadata={
                "file_name": original_filename or path.name,
                "topic": topic,
                "doc_date": doc_date,
                "url": url,
                "contact_name": contact_name,
                "contact_phone": contact_phone,
            },
            topic=topic,
            chunk_metas=[
                {
                    "chapter": c.get("chapter"),
                    "article": c.get("article"),
                    "path": c.get("path"),
                }
                for c in chunk_dicts
            ],
        )
        print(f"[RAG] qdrant 저장 완료 ({len(chunk_dicts)}개)")
        return len(chunk_dicts)


    def search(self, question: str, limit: int | None = None, source: str | None = None, topic: str | None = None) -> list[SearchResult]:
        return self.retriever.search(question=question, limit=limit, source=source, topic=topic)

    def search_context(self, question: str, limit: int | None = None, source: str | None = None, topic: str | None = None) -> str:
        return self.retriever.search_context(question=question, limit=limit, source=source, topic=topic)

    def search_context_with_results(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
        topic: str | None = None,
        original_question: str | None = None,
    ) -> tuple[str, list[SearchResult]]:
        results = self.retriever.search(
            question=question,
            limit=limit,
            source=source,
            topic=topic,
            original_question=original_question,
        )
        context = "\n\n".join(
            f"[source={self.format_source(result)}, score={result.score:.3f}]\n{result.text}"
            for result in results
            if result.text
        )
        return context, results

    def format_source(self, result: SearchResult) -> str:
        return (
            result.metadata.get("source")
            or result.metadata.get("file_name")
            or "unknown"
        )

    def primary_metadata(self, results: list[SearchResult], topic: str | None = None) -> dict:
        if not results:
            return {
                "source": None,
                "source_file": None,
                "topic": topic,
                "url": None,
                "contact_name": None,
                "contact_phone": None,
            }

        metadata = results[0].metadata
        return {
            "source": metadata.get("source"),
            "source_file": metadata.get("file_name"),
            "topic": metadata.get("topic") or topic,
            "url": metadata.get("url"),
            "contact_name": metadata.get("contact_name"),
            "contact_phone": metadata.get("contact_phone"),
        }


rag_service = RagService()