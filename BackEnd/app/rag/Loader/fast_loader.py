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

        suffix = path.suffix.lower()        #확장자 추출

        if suffix == ".pdf":                #PDF인지 확인
            return self._load_pdf(path)
        elif suffix == ".docx":             #DOCX인지 확인
            return self._load_docx(path)
        elif suffix in (".txt", ".md"):     #TXT / MD
            return self._load_text(path)
        elif suffix == ".pptx":             #PPTX
            return self._load_pptx(path)
        elif suffix == ".hwpx":             #HWPX (한글 XML 포맷)
            return self._load_hwpx(path)
        else:
            raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")

    def _load_pdf(self, path: Path) -> str:     #PDF 전용 함수
        import pdfplumber                       #PDF 텍스트 추출 라이브러리
        texts = []                              #빈 리스트 생성, 각 페이지 텍스트를 저장할 리스트
        with pdfplumber.open(path) as pdf:      #PDF 열기
            for page in pdf.pages:              #페이지 반복
                text = page.extract_text()      #텍스트 추출
                if text:
                    texts.append(text)          #리스트 저장
        result = "\n\n".join(texts)             #페이지 합치기
        if not result.strip():                  #빈 PDF 검사
            raise RuntimeError("PDF에서 텍스트를 추출할 수 없습니다. 스캔 문서일 수 있습니다.") #pdfplumber는 OCR이 없음 / 사진, 차트 안됨
        return result

    def _load_docx(self, path: Path) -> str:    #Word 전용 함수
        from docx import Document
        doc = Document(path)                    #문서 열기
        texts = [para.text for para in doc.paragraphs if para.text.strip()] #문단 추출

        # 표(Table) 안 텍스트도 추출 (문단만 읽으면 표 내용 누락됨)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text and cell_text not in texts:  # 중복 방지
                        texts.append(cell_text)

        return "\n\n".join(texts)               #합치기

    def _load_text(self, path: Path) -> str:                      #TXT / MD 전용
        return path.read_text(encoding="utf-8", errors="ignore")  #그대로 반환

    def _load_pptx(self, path: Path) -> str:    #PPT 전용
        from pptx import Presentation           #PPT 읽기 라이브러리
        prs = Presentation(path)                #PPT 열기
        texts = []
        for slide in prs.slides:                #슬라이드 반복
            for shape in slide.shapes:          #도형 반복 / PPT 안에는 텍스트박스, 제목, 표, 도형 등이 있음
                if hasattr(shape, "text") and shape.text.strip():   #텍스트 있는지 확인 / 빈 문자열 제외
                    texts.append(shape.text)    #저장
        return "\n\n".join(texts)               #합치기


    def _load_hwpx(self, path: Path) -> str:
        import zipfile
        from lxml import etree

        HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
        texts = []

        with zipfile.ZipFile(path, "r") as zf:
            section_files = sorted(
                f for f in zf.namelist()
                if f.startswith("Contents/section") and f.endswith(".xml")
            )
            for section in section_files:
                root = etree.fromstring(zf.read(section))
                for t in root.iter(f"{{{HP_NS}}}t"):
                    if t.text and t.text.strip():
                        texts.append(t.text.strip())

        result = "\n".join(texts)
        if not result.strip():
            raise RuntimeError("HWPX에서 텍스트를 추출할 수 없습니다.")
        return result


    def _load_hwp(self, path: Path) -> str:
        # HWP 바이너리 전용 (pyhwp 내부 XML 변환 후 Paragraph 단위로 텍스트 추출)
        import io
        from hwp5.xmlmodel import Hwp5File
        from contextlib import closing
        import xml.etree.ElementTree as ET
        
        output = io.BytesIO()
        with closing(Hwp5File(str(path))) as hwp5file:
            hwp5file.xmlevents().dump(output)
            
        xml_data = output.getvalue()
        root = ET.fromstring(xml_data)
        
        seen = set()
        paragraphs = []
        for p in root.iter('Paragraph'):
            texts = []
            for t in p.iter('Text'):
                if t.text:
                    texts.append(t.text)
            if texts:
                line = ''.join(texts).strip()
                # HWP 레이아웃 특성상 같은 문단이 중복 저장될 수 있어 dedup 처리
                if line and line not in seen:
                    seen.add(line)
                    paragraphs.append(line)

        text = '\n'.join(paragraphs)
        
        if not text.strip():
            raise RuntimeError("HWP에서 텍스트를 추출할 수 없습니다.")
        return text


# 모듈 수준 싱글턴 — 매번 FastLoader()를 새로 만들지 않고
# `from app.rag.Loader.fast_loader import fast_loader` 후 바로 사용 가능
fast_loader = FastLoader()