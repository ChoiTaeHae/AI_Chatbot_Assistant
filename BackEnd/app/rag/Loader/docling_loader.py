
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class DoclingLoader:

    def __init__(self, max_file_size_mb: int = 100) -> None:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend       #한글경로 리소스파일
        from docling.datamodel.base_models import InputFormat                       #Docling이 지원하는 파일 형식 열거형
        from docling.document_converter import DocumentConverter, PdfFormatOption   #DocumentConverter — 실제 변환 실행하는 핵심 클래스. PdfFormatOption — PDF 변환 옵션 설정 클래스.

        self.max_file_size_mb = max_file_size_mb
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    backend=PyPdfiumDocumentBackend,
                )
            }
        )

    def load_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        self._validate_file(path)

        try:
            result = self.converter.convert(str(path))
            document = result.document

            if hasattr(document, "export_to_markdown"):
                return document.export_to_markdown()

            if hasattr(document, "export_to_text"):
                return document.export_to_text()

            return str(document)

        except Exception as e:
            logger.exception("Docling 문서 변환 실패: %s", path)
            raise RuntimeError(f"문서 변환 실패: {path.name}") from e

    def _validate_file(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

        if not path.is_file():
            raise ValueError(f"파일이 아닙니다: {path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"PDF 파일만 지원합니다: {path}")

        file_size_mb = path.stat().st_size / 1024 / 1024

        if file_size_mb > self.max_file_size_mb:
            raise ValueError(
                f"파일이 너무 큽니다: {path.name} "
                f"({file_size_mb:.1f}MB > {self.max_file_size_mb}MB)"
            )

