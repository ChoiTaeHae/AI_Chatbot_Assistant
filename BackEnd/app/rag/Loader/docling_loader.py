
import logging              #로그를 남기기 위한 모듈
from pathlib import Path    #파일 경로를 객체로 다루기 위한 클래스

logger = logging.getLogger(__name__)    #현재 파일 전용 logger 생성

#region 파일 정보 딕셔너리 저장
SUPPORTED_EXTENSIONS = {    #지원하는 문서 형식
    ".pdf",
    ".docx",
    ".pptx",
}
#endregion

class DoclingLoader:

    def __init__(self, max_file_size_mb: int = 100) -> None:                        #객체 생성 시 자동 실행
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend       #한글경로 리소스파일, PDF 렌더링 엔진
        from docling.datamodel.base_models import InputFormat                       #Docling이 지원하는 파일 형식 열거형, 문서 형식 enum
        from docling.document_converter import DocumentConverter, PdfFormatOption   #DocumentConverter — 실제 변환 실행하는 핵심 클래스. PdfFormatOption — PDF 변환 옵션 설정 클래스.
        from docling.datamodel.pipeline_options import PdfPipelineOptions           #OCR 옵션

        pipeline_options = PdfPipelineOptions()     #PDF 파이프라인 생성
        pipeline_options.do_ocr = True              #OCR 활성화

        self.max_file_size_mb = max_file_size_mb       #최대 파일 크기 저장
        self.converter = DocumentConverter(            #Converter 생성, 실제 변환기 생성        #즉 PDF 읽기 가능, OCR 가능, Markdown 출력 가능
            format_options={                           #파일 형식별 설정
                InputFormat.PDF: PdfFormatOption(      #PDF에 대해서만 설정
                    backend=PyPdfiumDocumentBackend,   #PDF 처리 엔진
                    pipeline_options=pipeline_options  #OCR 옵션 전달
                )
            }
        )

    def load_text(self, file_path: str | Path) -> str:
        path = Path(file_path)          #문자열을 Path 객체로 변환
        self._validate_file(path)       #파일 검증(파일 존재? -> 파일인가? -> 지원 확장자인가?-> 용량 초과인가?)

        try:
            result = self.converter.convert(str(path))   #실제 문서 변환
            document = result.document                   #문서 객체 획득

            if hasattr(document, "export_to_markdown"):  #markdown 메서드 존재 여부 확인
                return document.export_to_markdown()     

            if hasattr(document, "export_to_text"):      #markdown 메서드 없으면 확인
                return document.export_to_text()

            return str(document)        #둘 다 없으면 객체를 문자열화

        except Exception as e:
            logger.exception("Docling 문서 변환 실패: %s", path)        #로그 예외처리
            raise RuntimeError(f"문서 변환 실패: {path.name}") from e   #재예외 발생

    def _validate_file(self, path: Path) -> None:   #문서 검증 함수
        if not path.exists():                       #파일 존재 확인
            raise FileNotFoundError(                #파일 없으면 실행
                f"파일을 찾을 수 없습니다: {path}"
            )

        if not path.is_file():                      #실제 파일인지 확인
            raise ValueError(                       #예외
                f"파일이 아닙니다: {path}"
            )

        suffix = path.suffix.lower()                        #확장자 확인

        if suffix not in SUPPORTED_EXTENSIONS:              #검사
            raise ValueError(                               #예외
                f"지원하지 않는 파일 형식입니다: {suffix}"
            )

        file_size_mb = path.stat().st_size / 1024 / 1024    #파일 크기 계산

        if file_size_mb > self.max_file_size_mb:            #최대 용량 검사
            raise ValueError(                               #예외
                f"파일이 너무 큽니다: {path.name} "
                f"({file_size_mb:.1f}MB > {self.max_file_size_mb}MB)"
            )

