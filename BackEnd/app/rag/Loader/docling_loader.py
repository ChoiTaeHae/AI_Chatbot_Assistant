from pathlib import Path


class DoclingLoader:
    """Load source documents and convert them into plain text for RAG."""

    def __init__(self) -> None:
        from docling.document_converter import DocumentConverter

        self.converter = DocumentConverter()

    def load_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        result = self.converter.convert(str(path))
        document = result.document

        if hasattr(document, "export_to_markdown"):
            return document.export_to_markdown()

        if hasattr(document, "export_to_text"):
            return document.export_to_text()

        return str(document)
