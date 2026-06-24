"""
OcrProcessor — Surya OCR 기반 통합 처리기

경로 1: 웹 크롤링 HTML → <img> 태그 이미지 → Surya OCR
경로 2: 이미지 파일 (.png / .jpg / .webp 등) → Surya OCR
경로 3: PDF → 텍스트 레이어 있으면 Docling 유지 / 없으면 Surya OCR 전체 처리

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

import logging
import re
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image

logger = logging.getLogger(__name__)

# PDF를 이미지로 변환할 때 해상도
PDF_DPI = 150
# 텍스트 레이어가 있는 PDF의 최소 텍스트 길이 (이 미만이면 스캔본으로 판단)
MIN_TEXT_FOR_NATIVE = 100


class OcrProcessor:
    """
    Surya OCR 기반 통합 OCR 처리기.
    한 번 생성하면 내부적으로 모델을 캐싱하므로
    RagService처럼 싱글턴으로 사용하는 것을 권장합니다.
    """

    def __init__(self) -> None:
        self._rec = None  # Surya RecognitionPredictor (지연 로딩)

    # =========================================================
    # 내부 모델 로더 (처음 사용할 때만 로드)
    # =========================================================

    @property
    def rec(self):
        """Surya RecognitionPredictor — 텍스트/표/이미지 블록 통합 인식 (지연 로딩)"""
        if self._rec is None:
            from surya.recognition import RecognitionPredictor
            logger.info("[OcrProcessor] Surya RecognitionPredictor 로딩 시작")
            self._rec = RecognitionPredictor()
            logger.info("[OcrProcessor] Surya RecognitionPredictor 로딩 완료")
        return self._rec

    # =========================================================
    # 경로 1: 웹 크롤링 HTML 처리
    # =========================================================

    def process_html(self, html: str, base_url: str = "") -> str:
        """
        HTML 문자열에서 텍스트를 추출합니다.
        - 일반 텍스트: BeautifulSoup으로 추출
        - <img> 태그: 이미지 다운로드 후 Surya OCR로 추출
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        for img_tag in soup.find_all("img"):
            src = img_tag.get("src", "")
            alt = img_tag.get("alt", "")

            if not src:
                continue

            img_url = urljoin(base_url, src) if base_url else src

            if img_url.startswith("data:image"):
                ocr_text = self._ocr_data_uri(img_url)
            elif img_url.startswith("http"):
                ocr_text = self._ocr_url(img_url)
            else:
                ocr_text = alt or ""

            if ocr_text:
                img_tag.replace_with(f"\n[이미지 텍스트: {ocr_text}]\n")
            elif alt:
                img_tag.replace_with(f"\n[이미지: {alt}]\n")
            else:
                img_tag.decompose()

        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # =========================================================
    # 경로 2: 이미지 파일 직접 처리
    # =========================================================

    def process_image(self, image_path: str | Path) -> str:
        """이미지 파일에서 텍스트를 추출합니다."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"이미지 파일 없음: {path}")

        logger.info("[OcrProcessor] 이미지 OCR 시작: %s", path.name)
        image = Image.open(path).convert("RGB")
        results = self.rec([image], full_page=True)
        text = self._extract_text_from_result(results[0])
        logger.info("[OcrProcessor] 이미지 OCR 완료: %d자", len(text))
        return text

    # =========================================================
    # 경로 3: PDF 처리 (Docling 결과와 병합)
    # =========================================================

    def process_pdf(self, pdf_path: str | Path, docling_text: str = "") -> str:
        """
        PDF에서 텍스트를 추출합니다.
        - 스캔본: 전체 페이지 Surya OCR
        - 텍스트 PDF: 이미지 블록만 Surya OCR로 보완 후 Docling 결과와 병합
        """
        import fitz

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF 파일 없음: {path}")

        doc = fitz.open(str(path))
        all_page_texts: list[str] = []
        is_scanned = len(docling_text.strip()) < MIN_TEXT_FOR_NATIVE

        logger.info(
            "[OcrProcessor] PDF 처리 시작: %s (%d페이지, %s)",
            path.name, len(doc),
            "스캔본→전체OCR" if is_scanned else "텍스트PDF→이미지블록보완",
        )

        for page_num, page in enumerate(doc):
            if is_scanned:
                page_text = self._ocr_full_page(page)
            else:
                page_text = self._ocr_image_blocks(page)

            if page_text:
                all_page_texts.append(f"[{page_num + 1}페이지]\n{page_text}")

        doc.close()
        ocr_text = "\n\n".join(all_page_texts)

        if is_scanned:
            logger.info("[OcrProcessor] 스캔본 OCR 완료: %d자", len(ocr_text))
            return ocr_text
        else:
            merged = self._merge_pdf_texts(docling_text, ocr_text)
            logger.info(
                "[OcrProcessor] PDF 병합 완료: Docling %d자 + OCR %d자 → %d자",
                len(docling_text), len(ocr_text), len(merged),
            )
            return merged

    # =========================================================
    # RagService.ingest_document()와 연결하는 헬퍼 메서드
    # =========================================================

    def load_text_with_ocr(self, file_path: str | Path) -> str:
        """
        파일 확장자에 따라 자동으로 처리 방식을 선택합니다.

        지원 확장자:
            - .pdf  → Docling 우선, 스캔본은 Surya OCR 전체 처리
            - .png / .jpg 등 이미지 → Surya OCR 직접 처리
            - .docx / .pptx → DoclingLoader 위임
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

        if suffix in IMAGE_EXTENSIONS:
            return self.process_image(path)
        elif suffix == ".pdf":
            docling_text = self._try_docling(path)
            return self.process_pdf(path, docling_text=docling_text)
        else:
            from app.rag.Loader import DoclingLoader
            return DoclingLoader().load_text(path)

    # =========================================================
    # PDF 내부 처리 헬퍼
    # =========================================================

    def _ocr_full_page(self, page) -> str:
        """페이지 전체를 이미지로 렌더링 후 Surya OCR (스캔본용)"""
        mat = page.get_pixmap(dpi=PDF_DPI)
        img = Image.frombytes(
            "RGB" if mat.n == 3 else "RGBA",
            (mat.width, mat.height),
            mat.samples,
        ).convert("RGB")
        results = self.rec([img], full_page=True)
        return self._extract_text_from_result(results[0])

    def _ocr_image_blocks(self, page) -> str:
        """텍스트 PDF에서 이미지 블록 영역만 선택적으로 Surya OCR 처리"""
        extracted_parts: list[str] = []

        blocks = page.get_text("dict")["blocks"]
        image_rects = [
            block["bbox"] for block in blocks if block.get("type") == 1
        ]

        for bbox in image_rects:
            clip = page.get_pixmap(dpi=PDF_DPI, clip=bbox)
            img = Image.frombytes(
                "RGB" if clip.n == 3 else "RGBA",
                (clip.width, clip.height),
                clip.samples,
            ).convert("RGB")

            results = self.rec([img], full_page=True)
            text = self._extract_text_from_result(results[0])
            if text:
                extracted_parts.append(f"[이미지 텍스트]\n{text}")

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
        """Docling 텍스트와 OCR 결과 병합."""
        if not ocr_text.strip():
            return docling_text
        if not docling_text.strip():
            return ocr_text
        return f"{docling_text}\n\n--- 이미지/표 OCR 결과 ---\n\n{ocr_text}"

    # =========================================================
    # 웹 이미지 처리 헬퍼
    # =========================================================

    def _ocr_url(self, url: str) -> str:
        """URL에서 이미지를 다운로드하고 Surya OCR 처리"""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                img_bytes = resp.read()
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            results = self.rec([img], full_page=True)
            return self._extract_text_from_result(results[0])
        except Exception as e:
            logger.debug("[OcrProcessor] 이미지 URL OCR 실패 (%s): %s", url[:60], e)
            return ""

    def _ocr_data_uri(self, data_uri: str) -> str:
        """data:image/...;base64,... 형식의 인라인 이미지 Surya OCR 처리"""
        try:
            import base64
            b64_data = data_uri.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            results = self.rec([img], full_page=True)
            return self._extract_text_from_result(results[0])
        except Exception as e:
            logger.debug("[OcrProcessor] data URI OCR 실패: %s", e)
            return ""

    # =========================================================
    # Surya 결과 파싱 헬퍼
    # =========================================================

    def _extract_text_from_result(self, page_result) -> str:
        """
        Surya PageOCRResult에서 텍스트 추출.

        - 표(Table) 블록: 행/열 구조 유지 → "셀1 | 셀2" 형식
        - 나머지 블록: HTML 태그 제거 후 순수 텍스트
        - reading_order 기준으로 정렬
        """
        if not page_result or not page_result.blocks:
            return ""

        from bs4 import BeautifulSoup

        parts: list[str] = []
        sorted_blocks = sorted(
            page_result.blocks,
            key=lambda b: getattr(b, "reading_order", 0),
        )

        for block in sorted_blocks:
            if block.skipped or not block.html:
                continue

            soup = BeautifulSoup(block.html, "html.parser")

            if block.label == "Table":
                rows = []
                for tr in soup.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    parts.append("\n".join(rows))
            else:
                text = soup.get_text(" ", strip=True)
                if text:
                    parts.append(text)

        return "\n\n".join(parts)


# 싱글턴 인스턴스
ocr_processor = OcrProcessor()


# =========================================================
# 테스트 실행 코드
# .venv2 환경에서: python app/rag/Loader/ocr_prosessor.py
# =========================================================
if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from pathlib import Path

    def print_header(msg):
        print(f"\n{'-'*50}\n{msg}\n{'-'*50}")

    processor = OcrProcessor()

    # 1. 이미지 파일 OCR 테스트
    test_img_path = "app/rag/Loader/test.png"
    print_header(f"테스트 1: 이미지 파일 OCR ({test_img_path})")
    if Path(test_img_path).exists():
        print(processor.process_image(test_img_path))
    else:
        print(f"'{test_img_path}' 파일이 없어서 건너뜁니다.")

    # 2. PDF 파일 OCR 테스트
    test_pdf_path = "app/rag/Loader/test.pdf"
    print_header(f"테스트 2: PDF 문서 처리 ({test_pdf_path})")
    if Path(test_pdf_path).exists():
        print(processor.process_pdf(test_pdf_path))
    else:
        print(f"'{test_pdf_path}' 파일이 없어서 건너뜁니다.")

    print("\n모든 테스트 종료.")
