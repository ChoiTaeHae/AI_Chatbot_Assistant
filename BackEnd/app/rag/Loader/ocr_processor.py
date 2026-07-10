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
MIN_TEXT_FOR_NATIVE = 500


class OcrProcessor:
    """
    Surya OCR 기반 통합 OCR 처리기.
    한 번 생성하면 내부적으로 모델을 캐싱하므로
    RagService처럼 싱글턴으로 사용하는 것을 권장합니다.
    """

    def __init__(self) -> None:
        self._rec = None
        self._foundation = None
        self._det = None

    # =========================================================
    # 내부 모델 로더 (처음 사용할 때만 로드)
    # =========================================================

    @property
    def models(self):
        """Surya 0.16.7 모델들 (지연 로딩)"""
        if self._rec is None:
            from surya.recognition import RecognitionPredictor
            from surya.foundation import FoundationPredictor
            from surya.detection import DetectionPredictor

            logger.info("[OcrProcessor] Surya Predictors 로딩 시작 (v0.16.7)")
            self._foundation = FoundationPredictor()
            self._det = DetectionPredictor()
            self._rec = RecognitionPredictor(self._foundation)
            logger.info("[OcrProcessor] Surya Predictors 로딩 완료")
        return self._rec, self._det

    def _run_ocr(self, images: list) -> list:
        rec, det = self.models
        results = rec(
            images,
            task_names=["ocr_with_boxes"] * len(images),
            det_predictor=det,
            math_mode=True,
        )
        return results

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
        results = self._run_ocr([image])
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
            path.name,
            len(doc),
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
        파일 확장자에 따라 자동으로 처리 방식을 선택합니다.
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
        import fitz
        mat = page.get_pixmap(dpi=PDF_DPI, colorspace=fitz.csRGB)
        img = Image.frombytes("RGB", (mat.width, mat.height), mat.samples)
        results = self._run_ocr([img])
        return self._extract_text_from_result(results[0])

    def _ocr_image_blocks(self, page) -> str:
        """텍스트 PDF에서 이미지 블록 영역만 선택적으로 Surya OCR 처리"""
        import fitz
        extracted_parts: list[str] = []

        blocks = page.get_text("dict")["blocks"]
        image_rects = [
            block["bbox"] for block in blocks if block.get("type") == 1
        ]

        for bbox in image_rects:
            clip = page.get_pixmap(dpi=PDF_DPI, clip=bbox, colorspace=fitz.csRGB)
            img = Image.frombytes("RGB", (clip.width, clip.height), clip.samples)
            results = self._run_ocr([img])
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
            results = self._run_ocr([img])
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
            results = self._run_ocr([img])
            return self._extract_text_from_result(results[0])
        except Exception as e:
            logger.debug("[OcrProcessor] data URI OCR 실패: %s", e)
            return ""

    # =========================================================
    # Surya 결과 파싱 헬퍼
    # =========================================================

    @staticmethod
    def _get_centers(line) -> tuple[float, float]:
        """polygon에서 x, y 중심좌표 반환"""
        poly = line.polygon
        x_center = sum(p[0] for p in poly) / len(poly)
        y_center = sum(p[1] for p in poly) / len(poly)
        return x_center, y_center

    def _extract_text_from_result(self, page_result) -> str:
        """
        Surya OCRResult에서 텍스트 추출.
        - polygon 좌표 기준으로 행 재정렬
        - 다중 컬럼 비율이 30% 이상이면 표로 판단 → 컬럼 분리 후 문맥 복원
        - 일반 문서면 행 순서대로 단순 병합
        """
        if not page_result or not getattr(page_result, "text_lines", None):
            return ""

        lines = [
            line for line in page_result.text_lines
            if getattr(line, "text", "").strip()
        ]
        if not lines:
            return ""

        # 행 높이 평균으로 같은 행 판단 기준(tolerance) 계산
        heights = [
            max(p[1] for p in l.polygon) - min(p[1] for p in l.polygon)
            for l in lines
        ]
        avg_height = sum(heights) / len(heights) if heights else 20
        tolerance = avg_height * 0.6

        # y좌표 기준으로 행 그룹핑
        rows: list[list] = []
        for line in lines:
            _, y_center = self._get_centers(line)
            placed = False
            for row in rows:
                row_y = sum(self._get_centers(l)[1] for l in row) / len(row)
                if abs(y_center - row_y) <= tolerance:
                    row.append(line)
                    placed = True
                    break
            if not placed:
                rows.append([line])

        # 위→아래 순서로 행 정렬
        rows.sort(key=lambda row: sum(self._get_centers(l)[1] for l in row) / len(row))

        # 한 행에 텍스트가 2개 이상인 행이 30% 이상이면 표로 판단
        multi_col_rows = sum(1 for row in rows if len(row) >= 2)
        is_table = (multi_col_rows / len(rows)) >= 0.3 if rows else False
        logger.info("[OcrProcessor] 표 감지: is_table=%s, multi_col=%d/%d", is_table, multi_col_rows, len(rows))

        if not is_table:
            # 일반 문서: x순서대로 정렬 후 한 줄로 병합
            result_lines = []
            for row in rows:
                row.sort(key=lambda l: self._get_centers(l)[0])
                result_lines.append(" ".join(l.text for l in row))
            return "\n".join(result_lines)

        # 표 문서: x좌표 gap이 가장 큰 지점을 컬럼 경계로 자동 탐지
        all_x = sorted(set(round(self._get_centers(l)[0]) for l in lines))
        col_split = all_x[len(all_x) // 2]  # 기본값: 중앙
        max_gap = 0
        for i in range(1, len(all_x)):
            gap = all_x[i] - all_x[i - 1]
            if gap > max_gap:
                max_gap = gap
                col_split = (all_x[i] + all_x[i - 1]) / 2

        logger.debug("[OcrProcessor] 표 감지 → col_split=%.0f", col_split)

        result_lines = []
        prev_left = ""
        for row in rows:
            row.sort(key=lambda l: self._get_centers(l)[0])
            left_texts = [l.text for l in row if self._get_centers(l)[0] <= col_split]
            right_texts = [l.text for l in row if self._get_centers(l)[0] > col_split]
            left = " ".join(left_texts).strip()
            right = " ".join(right_texts).strip()

            # 왼쪽 컬럼이 비면 병합 셀 → 이전 값 유지
            if not left:
                left = prev_left
            else:
                prev_left = left

            if left and right:
                result_lines.append(f"{left}: {right}")
            elif right:
                result_lines.append(right)
            elif left:
                result_lines.append(left)

        return "\n".join(result_lines)