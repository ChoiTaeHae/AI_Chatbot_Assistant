from __future__ import annotations

import argparse

from app.imsi.crawler import DEFAULT_NOTICE_URL, crawl_notice_page
from app.rag.Chunking import split_by_length
from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval import QdrantVectorStore


def ingest_notice_page(url: str = DEFAULT_NOTICE_URL, source: str = "tech_notice_267227") -> int:
    page = crawl_notice_page(url)
    document_text = page.to_document_text()
    chunks = split_by_length(document_text, chunk_size=800, overlap=120)

    if not chunks:
        print("[IMSI] No chunks created")
        return 0

    embedding = BaaiEmbedding()
    vector_store = QdrantVectorStore()

    print(f"[IMSI] Crawled: {page.title}")
    print(f"[IMSI] Chunks: {len(chunks)}")
    embeddings = embedding.embed_texts(chunks)

    vector_store.upsert_chunks(
        chunks=chunks,
        embeddings=embeddings,
        source=source,
        metadata=page.metadata(),
    )
    print(f"[IMSI] Upserted to Qdrant: source={source}")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl a school notice page and ingest it into Qdrant.")
    parser.add_argument("--url", default=DEFAULT_NOTICE_URL, help="School notice page URL to crawl.")
    parser.add_argument("--source", default="tech_notice_267227", help="Source name stored in Qdrant payload.")
    args = parser.parse_args()

    ingest_notice_page(url=args.url, source=args.source)


if __name__ == "__main__":
    main()

