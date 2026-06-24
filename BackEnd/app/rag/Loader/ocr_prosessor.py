"""
OcrProcessor — 세 가지 입력 경로의 OCR을 통합 처리하는 클래스

경로 1: 웹 크롤링 HTML → <img> 태그 이미지 → PaddleOCR
경로 2: 이미지 파일 (.png / .jpg / .webp) → PaddleOCR
경로 3: PDF → 텍스트 레이어 있으면 Docling 유지 / 없으면 PaddleOCR / 표는 항상 PaddleOCR

사용법:
    from app.rag.Loader.ocr_processor import OcrProcessor
    processor = OcrProcessor()

    # 이미지 파일
    text = processor.process_image("path/to/image.png")

    # PDF (표/이미지 포함)
    text = processor.process_pdf("path/to/file.pdf", docling_text="기존 Docling 결과")

    # 웹 크롤링 HTML
    text = processor.process_html(html_str, base_url="https://...")
"""

from __future__ import annotations

import os
# 🚨 Windows CPU 환경에서 발생하는 OneDNN(MKLDNN) fused_conv2d 충돌 버그를 원천 차단합니다.
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_enable_mkldnn"] = "0"

import logging
import re
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# PDF를 이미지로 변환할 때 해상도 (높을수록 정확하지만 느림)
PDF_DPI = 150
# 표 인식 최소 신뢰도 (0~1)
TABLE_CONFIDENCE = 0.7
# 텍스트 레이어가 있는 PDF의 최소 텍스트 길이 (이 미만이면 스캔본으로 판단)
MIN_TEXT_FOR_NATIVE = 100


class OcrProcessor:
    """
    PaddleOCR 기반 통합 OCR 처리기.
    한 번 생성하면 내부적으로 모델을 캐싱하므로
    RagService처럼 싱글턴으로 사용하는 것을 권장합니다.
    """

    def __init__(self) -> None:
        self._ocr = None        # PaddleOCR 일반 텍스트 인식 모델
        self._table_ocr = None  # PaddleOCR 표 구조 인식 모델

    # =========================================================
    # 내부 모델 로더 (처음 사용할 때만 로드)
    # =========================================================

    @property
    def ocr(self):
        """일반 텍스트/이미지 인식용 PaddleOCR 모델 (지연 로딩)"""
        if self._ocr is None:
            from paddleocr import PaddleOCR
            logger.info("[OcrProcessor] PaddleOCR 텍스트 모델 로딩")
            self._ocr = PaddleOCR(
                use_angle_cls=True,       # 회전된 텍스트 감지 (경고 메시지 해결)
                lang="korean",            # 한국어 + 영어 동시 인식
                use_gpu=False,            # CPU 명시적 사용
                show_log=False,           # 터미널 지저분해지는 것 방지
                enable_mkldnn=False,      # 치명적인 윈도우 CPU OneDNN 버그 방지
                ir_optim=False,           # Paddle 내부의 버그성 자동 최적화(fused_conv2d) 강제 종료
                det_limit_side_len=2048,  # 이미지 축소 제한을 풀어 작은 글씨도 정밀하게 탐지
                det_db_score_mode="slow", # 속도보다는 정확도 위주로 탐색
            )
            logger.info("[OcrProcessor] PaddleOCR 텍스트 모델 로딩 완료")
        return self._ocr

    @property
    def table_ocr(self):
        """표 구조 인식용 PaddleOCR 모델 (지연 로딩)"""
        if self._table_ocr is None:
            from paddleocr import PPStructure
            logger.info("[OcrProcessor] PaddleOCR 표 모델 로딩")
            self._table_ocr = PPStructure(
                lang="korean",
                use_gpu=False,
                show_log=False,
                enable_mkldnn=False,  # OneDNN 버그 방지
                ir_optim=False,       # 표 인식 모델에서도 최적화 종료
            )
            logger.info("[OcrProcessor] PaddleOCR 표 모델 로딩 완료")
        return self._table_ocr

    # =========================================================
    # 경로 1: 웹 크롤링 HTML 처리
    # =========================================================

    def process_html(self, html: str, base_url: str = "") -> str:
        """
        HTML 문자열에서 텍스트를 추출합니다.
        - 일반 텍스트: BeautifulSoup으로 추출 (기존 크롤러 방식 유지)
        - <img> 태그: 이미지 다운로드 후 PaddleOCR로 추출
        - 추출된 텍스트를 원래 위치에 [이미지 텍스트: ...] 형태로 삽입

        Args:
            html: 크롤링한 HTML 문자열
            base_url: 상대 URL 해석용 베이스 URL

        Returns:
            텍스트 + 이미지 OCR 결과가 합쳐진 문자열
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # <img> 태그마다 OCR 텍스트로 대체
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src", "")
            alt = img_tag.get("alt", "")

            if not src:
                continue

            # 상대 URL → 절대 URL 변환
            img_url = urljoin(base_url, src) if base_url else src

            # data URI (base64 인라인 이미지) 처리
            if img_url.startswith("data:image"):
                ocr_text = self._ocr_data_uri(img_url)
            elif img_url.startswith("http"):
                ocr_text = self._ocr_url(img_url)
            else:
                # 로컬 경로면 alt 텍스트만 사용
                ocr_text = alt or ""

            if ocr_text:
                # <img> 태그를 OCR 결과 텍스트로 대체
                img_tag.replace_with(f"\n[이미지 텍스트: {ocr_text}]\n")
            elif alt:
                img_tag.replace_with(f"\n[이미지: {alt}]\n")
            else:
                img_tag.decompose()

        # 나머지 HTML 텍스트 추출
        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # =========================================================
    # 경로 2: 이미지 파일 직접 처리
    # =========================================================

    def process_image(self, image_path: str | Path) -> str:
        """
        이미지 파일(.png / .jpg / .webp 등)에서 텍스트를 추출합니다.

        Args:
            image_path: 이미지 파일 경로

        Returns:
            추출된 텍스트 문자열
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"이미지 파일 없음: {path}")

        logger.info("[OcrProcessor] 이미지 OCR 시작: %s", path.name)
        result = self.ocr.ocr(str(path), cls=True)
        text = self._extract_text_from_result(result)
        logger.info("[OcrProcessor] 이미지 OCR 완료: %d자", len(text))
        return text

    # =========================================================
    # 경로 3: PDF 처리 (Docling 결과와 병합)
    # =========================================================

    def process_pdf(
        self,
        pdf_path: str | Path,
        docling_text: str = "",
    ) -> str:
        """
        PDF에서 표와 이미지를 PaddleOCR로 추가 추출하고 Docling 텍스트와 병합합니다.

        처리 흐름:
        1. Docling 텍스트가 충분하면 → 표/이미지 영역만 PaddleOCR로 보완
        2. Docling 텍스트가 없거나 너무 짧으면 (스캔본) → 전체 페이지 PaddleOCR

        Args:
            pdf_path: PDF 파일 경로
            docling_text: DoclingLoader.load_text()가 반환한 텍스트 (없으면 빈 문자열)

        Returns:
            최종 병합 텍스트
        """
        import fitz  # PyMuPDF

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF 파일 없음: {path}")

        doc = fitz.open(str(path))
        all_page_texts: list[str] = []

        is_scanned = len(docling_text.strip()) < MIN_TEXT_FOR_NATIVE

        logger.info(
            "[OcrProcessor] PDF 처리 시작: %s (%d페이지, %s)",
            path.name,
            len(doc),
            "스캔본→전체OCR" if is_scanned else "텍스트PDF→표/이미지보완",
        )

        for page_num, page in enumerate(doc):
            if is_scanned:
                # 스캔본: 페이지 전체를 이미지로 변환 후 PaddleOCR
                page_text = self._ocr_full_page(page)
            else:
                # 텍스트 PDF: 표와 이미지 영역만 PaddleOCR로 추출
                page_text = self._ocr_tables_and_images(page)

            if page_text:
                all_page_texts.append(f"[{page_num + 1}페이지]\n{page_text}")

        doc.close()

        ocr_text = "\n\n".join(all_page_texts)

        if is_scanned:
            # 스캔본: OCR 결과가 전부
            logger.info("[OcrProcessor] 스캔본 OCR 완료: %d자", len(ocr_text))
            return ocr_text
        else:
            # 텍스트 PDF: Docling 텍스트 + 표/이미지 OCR 결과 병합
            merged = self._merge_pdf_texts(docling_text, ocr_text)
            logger.info(
                "[OcrProcessor] PDF 병합 완료: Docling %d자 + OCR %d자 → %d자",
                len(docling_text),
                len(ocr_text),
                len(merged),
            )
            return merged

    # =========================================================
    # RagService.ingest_document()와 연결하는 헬퍼 메서드
    # =========================================================

    def load_text_with_ocr(self, file_path: str | Path) -> str:
        """
        파일 확장자에 따라 자동으로 적절한 처리 방식을 선택합니다.
        RagService.ingest_document() 안에서 기존 DoclingLoader 대신 호출하세요.

        지원 확장자:
            - .pdf  → Docling 우선, 표/스캔본은 PaddleOCR 보완
            - .png / .jpg / .jpeg / .webp / .bmp → PaddleOCR 직접 처리
            - .docx / .pptx → DoclingLoader 위임 (OCR 불필요)

        Returns:
            추출된 텍스트 문자열
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

        if suffix in IMAGE_EXTENSIONS:
            # 이미지 파일 → PaddleOCR 직접 처리
            return self.process_image(path)

        elif suffix == ".pdf":
            # PDF → Docling 먼저 시도, 결과를 OcrProcessor에 넘겨서 보완
            docling_text = self._try_docling(path)
            return self.process_pdf(path, docling_text=docling_text)

        else:
            # .docx / .pptx 등 → DoclingLoader 그대로 사용
            from app.rag.Loader import DoclingLoader
            return DoclingLoader().load_text(path)

    # =========================================================
    # PDF 내부 처리 헬퍼
    # =========================================================

    def _ocr_full_page(self, page) -> str:
        """페이지 전체를 이미지로 렌더링 후 PaddleOCR 처리 (스캔본용)"""
        import numpy as np

        mat = page.get_pixmap(dpi=PDF_DPI)
        img_array = np.frombuffer(mat.samples, dtype=np.uint8).reshape(
            mat.height, mat.width, mat.n
        )

        # RGBA → RGB 변환 (PaddleOCR는 4채널 미지원)
        if mat.n == 4:
            import cv2
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)

        result = self.ocr.ocr(img_array, cls=True)
        return self._extract_text_from_result(result)

    def _ocr_tables_and_images(self, page) -> str:
        """
        텍스트 PDF에서 표와 이미지 영역만 선택적으로 OCR 처리.
        PyMuPDF로 이미지 블록과 표 영역을 감지합니다.
        """
        import numpy as np

        extracted_parts: list[str] = []

        # 페이지에서 이미지 블록 위치 감지
        blocks = page.get_text("dict")["blocks"]
        image_rects = [
            block["bbox"]
            for block in blocks
            if block.get("type") == 1  # type 1 = 이미지 블록
        ]

        for bbox in image_rects:
            # 해당 영역만 잘라서 이미지로 변환
            clip = page.get_pixmap(dpi=PDF_DPI, clip=bbox)
            img_array = np.frombuffer(clip.samples, dtype=np.uint8).reshape(
                clip.height, clip.width, clip.n
            )

            if clip.n == 4:
                import cv2
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)

            # 표 구조 인식 시도
            table_result = self.table_ocr(img_array)
            table_text = self._extract_table_text(table_result)

            if table_text:
                extracted_parts.append(f"[표]\n{table_text}")
            else:
                # 표가 아니면 일반 OCR
                ocr_result = self.ocr.ocr(img_array, cls=True)
                plain_text = self._extract_text_from_result(ocr_result)
                if plain_text:
                    extracted_parts.append(f"[이미지 텍스트]\n{plain_text}")

        return "\n\n".join(extracted_parts)

    def _try_docling(self, path: Path) -> str:
        """Docling으로 PDF 텍스트 추출 시도. 실패하면 빈 문자열 반환."""
        try:
            from app.rag.Loader import DoclingLoader
            return DoclingLoader().load_text(path)
        except Exception as e:
            logger.warning("[OcrProcessor] Docling 실패 → 전체 OCR로 대체: %s", e)
            return ""

    def _merge_pdf_texts(self, docling_text: str, ocr_text: str) -> str:
        """Docling 텍스트와 OCR 결과 병합. OCR 내용을 문서 끝에 추가."""
        if not ocr_text.strip():
            return docling_text
        if not docling_text.strip():
            return ocr_text
        return f"{docling_text}\n\n--- 이미지/표 OCR 결과 ---\n\n{ocr_text}"

    # =========================================================
    # 웹 이미지 처리 헬퍼
    # =========================================================

    def _ocr_url(self, url: str) -> str:
        """URL에서 이미지를 다운로드하고 OCR 처리"""
        try:
            import numpy as np
            from PIL import Image

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                img_bytes = resp.read()

            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            img_array = np.array(img)
            result = self.ocr.ocr(img_array, cls=True)
            return self._extract_text_from_result(result)

        except Exception as e:
            logger.debug("[OcrProcessor] 이미지 URL OCR 실패 (%s): %s", url[:60], e)
            return ""

    def _ocr_data_uri(self, data_uri: str) -> str:
        """data:image/...;base64,... 형식의 인라인 이미지 OCR 처리"""
        try:
            import base64
            import numpy as np
            from PIL import Image

            # "data:image/png;base64,xxxx" → "xxxx"
            b64_data = data_uri.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            img_array = np.array(img)
            result = self.ocr.ocr(img_array, cls=True)
            return self._extract_text_from_result(result)

        except Exception as e:
            logger.debug("[OcrProcessor] data URI OCR 실패: %s", e)
            return ""

    # =========================================================
    # PaddleOCR 결과 파싱 헬퍼
    # =========================================================

    def _extract_text_from_result(self, result) -> str:
        """
        PaddleOCR.ocr() 반환값에서 텍스트만 추출.

        반환 형식: [[ [bbox, (text, confidence)], ... ], ...]
        """
        if not result:
            return ""

        lines: list[str] = []
        for page_result in result:
            if not page_result:
                continue
            for line in page_result:
                if not line or len(line) < 2:
                    continue
                text_info = line[1]
                if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                    text = str(text_info[0]).strip()
                    confidence = float(text_info[1]) if len(text_info) >= 2 else 1.0
                    # 신뢰도가 너무 낮은 결과 제외
                    # 배경 무늬를 이상한 글자로 오인한 쓰레기 텍스트 버리기
                    if text and confidence >= 0.65:
                        lines.append(text)

        return "\n".join(lines)

    def _extract_table_text(self, table_result) -> str:
        """
        PPStructure (표 인식) 반환값에서 텍스트 추출.
        HTML 표 형태로 반환되므로 텍스트만 추출합니다.
        """
        if not table_result:
            return ""

        texts: list[str] = []
        for region in table_result:
            region_type = region.get("type", "")
            if region_type != "table":
                continue

            confidence = region.get("score", 0)
            if confidence < TABLE_CONFIDENCE:
                continue

            # HTML 형식의 표 결과에서 텍스트 추출
            html_table = region.get("res", {}).get("html", "")
            if html_table:
                from bs4 import BeautifulSoup
                table_soup = BeautifulSoup(html_table, "html.parser")
                rows = []
                for tr in table_soup.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    texts.append("\n".join(rows))

        return "\n\n".join(texts)


# 싱글턴 인스턴스 (RagService처럼 모듈 레벨에서 생성)
ocr_processor = OcrProcessor()

# =========================================================
# 🚀 테스트 실행 코드
# 터미널에서 `python app/rag/Loader/ocr_prosessor.py`로 실행 시 작동
# =========================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    def print_header(msg): print(f"\n{'-'*50}\n🚀 {msg}\n{'-'*50}")
    
    processor = OcrProcessor()
    
    # -----------------------------------------------------
    # 1. HTML 크롤링 + 웹 이미지 OCR 테스트
    # -----------------------------------------------------
    print_header("테스트 1: HTML 내의 웹 이미지 OCR 추출")
    sample_html = """
    <div>
        <p>크롤링한 웹페이지입니다. 아래 이미지를 읽어보세요.</p>
        <img src="https://dummyimage.com/600x200/000/fff&text=PaddleOCR+HTML+Test" alt="테스트이미지">
    </div>
    """
    html_result = processor.process_html(sample_html)
    print(html_result)

    # -----------------------------------------------------
    # 2. 로컬 이미지 파일 OCR 테스트
    # -----------------------------------------------------
    # BackEnd 폴더에서 실행하므로 경로를 맞춰줍니다.
    test_img_path = "app/rag/Loader/test.png"  
    print_header(f"테스트 2: 로컬 이미지 파일 ({test_img_path})")
    
    if Path(test_img_path).exists():
        img_result = processor.process_image(test_img_path)
        print(img_result)
    else:
        print(f"⚠️ '{test_img_path}' 파일이 없어서 건너뜁니다.")

    # -----------------------------------------------------
    # 3. PDF 파일 OCR + 표 추출 테스트
    # -----------------------------------------------------
    test_pdf_path = "app/rag/Loader/test.pdf"
    print_header(f"테스트 3: PDF 문서 처리 ({test_pdf_path})")
    
    if Path(test_pdf_path).exists():
        pdf_result = processor.process_pdf(test_pdf_path)
        print(pdf_result)
    else:
        print(f"⚠️ '{test_pdf_path}' 파일이 없어서 건너뜁니다.")
        
    print("\n✅ 모든 테스트가 종료되었습니다.")