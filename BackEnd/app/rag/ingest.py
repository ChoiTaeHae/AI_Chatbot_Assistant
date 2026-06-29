import argparse
from pathlib import Path

from app.services.rag_service import RagService


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".hwpx", ".hwp"}


def ingest_file(
    file_path: str | Path,
    source: str | None = None,
    service: RagService | None = None,
    topic: str | None = None,
    doc_date: str | None = None,
    url: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
) -> int:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    rag_service = service or RagService()
    source_name = source or path.stem

    print(f"[RAG] Ingesting document: {path}")
    chunk_count = rag_service.ingest_document(
        file_path=path,
        source=source_name,
        topic=topic,
        doc_date=doc_date,
        url=url,
        contact_name=contact_name,
        contact_phone=contact_phone,
    )

    if chunk_count == 0:
        print("[RAG] No chunks created")
        return 0

    print(f"[RAG] Ingest complete: {chunk_count} chunks")
    return chunk_count


def ingest_directory(directory_path: str | Path, source_prefix: str | None = None) -> int:
    directory = Path(directory_path)

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    rag_service = RagService()
    total_chunks = 0

    for file_path in files:
        source = f"{source_prefix}:{file_path.stem}" if source_prefix else file_path.stem
        total_chunks += ingest_file(
            file_path=file_path,
            source=source,
            service=rag_service,
        )

    print(f"[RAG] Directory ingest complete: {len(files)} files, {total_chunks} chunks")
    return total_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into Qdrant for RAG.")
    parser.add_argument("--file", help="Single document path to ingest.")
    parser.add_argument("--dir", help="Directory path to ingest recursively.")
    parser.add_argument("--source", help="Source name stored in Qdrant payload.")
    parser.add_argument("--topic", help="Topic tag stored in Qdrant payload.")
    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("one of --file or --dir is required")

    if args.file and args.dir:
        parser.error("use only one of --file or --dir")

    if args.file:
        ingest_file(args.file, source=args.source, topic=args.topic)
        return

    ingest_directory(args.dir, source_prefix=args.source)


if __name__ == "__main__":
    main()