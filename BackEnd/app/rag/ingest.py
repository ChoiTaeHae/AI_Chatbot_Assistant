import argparse
from pathlib import Path

from app.rag.Chunking import split_by_article
from app.rag.Embedding import BaaiEmbedding
from app.rag.Loader import DoclingLoader
from app.rag.Retrieval import QdrantVectorStore


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}


def ingest_file(file_path: str | Path, source: str | None = None) -> int:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    source_name = source or path.stem
    loader = DoclingLoader()
    embedding = BaaiEmbedding()
    vector_store = QdrantVectorStore()

    print(f"[RAG] Loading document: {path}")
    text = loader.load_text(path)

    print("[RAG] Splitting chunks")
    chunks = split_by_article(text)
    if not chunks:
        print("[RAG] No chunks created")
        return 0

    print(f"[RAG] Embedding chunks: {len(chunks)}")
    embeddings = embedding.embed_texts(chunks)

    print(f"[RAG] Upserting to Qdrant: source={source_name}")
    vector_store.upsert_chunks(
        chunks=chunks,
        embeddings=embeddings,
        source=source_name,
        metadata={"file_name": path.name},
    )

    print(f"[RAG] Ingest complete: {len(chunks)} chunks")
    return len(chunks)


def ingest_directory(directory_path: str | Path, source_prefix: str | None = None) -> int:
    directory = Path(directory_path)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    total_chunks = 0
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    for file_path in files:
        source = f"{source_prefix}:{file_path.stem}" if source_prefix else file_path.stem
        total_chunks += ingest_file(file_path, source=source)

    print(f"[RAG] Directory ingest complete: {len(files)} files, {total_chunks} chunks")
    return total_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into Qdrant for RAG.")
    parser.add_argument("--file", help="Single document path to ingest.")
    parser.add_argument("--dir", help="Directory path to ingest recursively.")
    parser.add_argument("--source", help="Source name stored in Qdrant payload.")
    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("one of --file or --dir is required")

    if args.file and args.dir:
        parser.error("use only one of --file or --dir")

    if args.file:
        ingest_file(args.file, source=args.source)
        return

    ingest_directory(args.dir, source_prefix=args.source)


if __name__ == "__main__":
    main()
