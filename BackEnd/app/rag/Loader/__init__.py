from app.rag.Loader.docling_loader import DoclingLoader
from app.rag.Loader.ocr_processor import OcrProcessor  # 클래스만 export, 싱글턴은 RagService 내부에서 관리

__all__ = ["DoclingLoader", "OcrProcessor"]