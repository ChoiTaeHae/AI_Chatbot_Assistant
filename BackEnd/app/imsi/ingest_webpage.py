from __future__ import annotations

import argparse
import traceback

from app.imsi.crawler import DEFAULT_NOTICE_URL, crawl_notice_page
from app.rag.Chunking import smart_split
from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval import QdrantVectorStore


def ingest_notice_page(
    url: str = DEFAULT_NOTICE_URL,
    source: str = "tech_notice_267227",
    topic: str = "notice",
) -> int:
    page = crawl_notice_page(url)
    document_text = page.to_document_text()
    raw_chunks = smart_split(document_text, chunk_size=1000, overlap=200)

    if not raw_chunks:
        print("[IMSI] No chunks created")
        return 0

    texts = [c["text"] for c in raw_chunks]
    embedding_texts = [c["embedding_text"] for c in raw_chunks]
    chunk_metas = [{"chapter": c["chapter"], "article": c["article"], "path": c["path"]} for c in raw_chunks]

    embedding = BaaiEmbedding()
    vector_store = QdrantVectorStore()

    print(f"[IMSI] Crawled: {page.title}", flush=True)
    print(f"[IMSI] Chunks: {len(texts)}", flush=True)

    print("[IMSI] Embedding start", flush=True)
    embeddings = embedding.embed_texts(embedding_texts)
    print(f"[IMSI] Embedding done: {len(embeddings)} vectors", flush=True)

    print("[IMSI] Qdrant upsert start", flush=True)

    vector_store.upsert_chunks(
        chunks=texts,
        embeddings=embeddings,
        source=source,
        metadata=page.metadata(),
        topic=topic,
        chunk_metas=chunk_metas,
    )

    print(f"[IMSI] Upserted to Qdrant: source={source}, topic={topic}")
    return len(texts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl a school notice page and ingest it into Qdrant."
    )

    parser.add_argument(
        "--url",
        default=DEFAULT_NOTICE_URL,
        help="School notice page URL to crawl.",
    )

    parser.add_argument(
        "--source",
        default="tech_notice_267227",
        help="Source name stored in Qdrant payload.",
    )

    parser.add_argument(
        "--topic",
        default="notice",
        help="Topic name.",
    )

    args = parser.parse_args()

    try:
        ingest_notice_page(
            url=args.url,
            source=args.source,
            topic=args.topic,
        )

    except Exception:
        print("[IMSI] Ingest failed", flush=True)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()