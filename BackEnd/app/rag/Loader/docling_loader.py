from pathlib import Path


class DoclingLoader:
    """Load source documents and convert them into plain text for RAG."""

    def load_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._load_pdf(path)
        elif suffix in {".docx", ".doc"}:
            return self._load_docx(path)
        else:
            return path.read_text(encoding="utf-8", errors="ignore")

    def _load_pdf(self, path: Path) -> str:
        import pdfplumber
        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
        return "\n".join(texts)

    def _load_docx(self, path: Path) -> str:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
