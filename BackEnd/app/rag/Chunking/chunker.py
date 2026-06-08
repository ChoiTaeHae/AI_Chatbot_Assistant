import re

ARTICLE_PATTERN = re.compile(r"(제\s*\d+\s*조(?:의\d+)?\s*\(.*?\))")

def split_by_article(
    text: str,
    min_length: int = 50,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[str]:
    """Split Korean regulation-style documents by article title."""
    parts = ARTICLE_PATTERN.split(text)

    if len(parts) <= 1:
        return split_by_length(
            text,
            chunk_size=chunk_size,
            overlap=overlap,
            min_length=min_length,
        )

    chunks: list[str] = []

    for index in range(1, len(parts), 2):
        title = parts[index]
        body = parts[index + 1] if index + 1 < len(parts) else ""
        chunk = f"{title}{body}".strip()

        if len(chunk) < min_length:
            continue

        if len(chunk) > chunk_size:
            chunks.extend(
                split_by_length(
                    chunk,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    min_length=min_length,
                )
            )
            continue

        chunks.append(chunk)

    return chunks

def split_by_length(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
    min_length: int = 50,
) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    normalized = re.sub(r"\s+", " ", text).strip()
    chunks: list[str] = []
    start = 0

    while start < len(normalized):
        end = start + chunk_size
        chunk = normalized[start:end].strip()

        if len(chunk) >= min_length:
            chunks.append(chunk)

        start = end - overlap if end < len(normalized) else end

    return chunks