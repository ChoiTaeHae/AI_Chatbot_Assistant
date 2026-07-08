"""(임시) 특정 문서의 저장된 청크 텍스트 확인 — OCR/추출 품질 점검용"""
from app.core.Qdrant import qdrant_client
from app.core.config import settings

KEY = "푸른빛"
col = settings.QDRANT_COLLECTION

points, _ = qdrant_client.scroll(
    collection_name=col, limit=2000, with_payload=True, with_vectors=False,
)
matched = [p for p in points if KEY in (p.payload.get("source") or "")]
matched.sort(key=lambda p: p.payload.get("chunk_index", 0))

print(f"=== '{KEY}' 포함 청크 {len(matched)}개 ===\n")
for p in matched:
    pl = p.payload
    print(f"[idx={pl.get('chunk_index')}] topic={pl.get('topic')} len={len(pl.get('text',''))}")
    print(f"  text: {repr(pl.get('text',''))}")
    print()
