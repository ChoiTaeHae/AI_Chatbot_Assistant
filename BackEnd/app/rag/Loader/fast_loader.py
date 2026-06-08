"""
빠른 문서 로더 - pdfplumber / python-docx / 텍스트 직접 읽기
Docling 대비 훨씬 빠름 (ML 모델 없이 규칙 기반 파싱)
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FastLoader:

    def load_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._load_pdf(path)
        elif suffix == ".docx":
            return self._load_docx(path)
        elif suffix in (".txt", ".md"):
            return self._load_text(path)
        elif suffix == ".pptx":
            return self._load_pptx(path)
        else:
            raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")

    def _load_pdf(self, path: Path) -> str:
        import pdfplumber
        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
        result = "\n\n".join(texts)
        if not result.strip():
            raise RuntimeError("PDF에서 텍스트를 추출할 수 없습니다. 스캔 문서일 수 있습니다.")
        return result

    def _load_docx(self, path: Path) -> str:
        from docx import Document
        doc = Document(path)
        texts = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n\n".join(texts)

    def _load_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="ignore")

    def _load_pptx(self, path: Path) -> str:
        from pptx import Presentation
        prs = Presentation(path)
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text)
        return "\n\n".join(texts)


fast_loader = FastLoader()
