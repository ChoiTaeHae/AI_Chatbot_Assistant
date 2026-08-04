# -*- coding: utf-8 -*-
"""저장된 청크 원문 확인 — OCR·추출·청킹 품질 점검용.

실행 (백엔드 컨테이너 안에서):
    docker exec ai_chatbot_assistant-backend-1 sh -c \\
        'cd /app && python3 scripts/inspect_chunks.py 푸른빛'

    scripts/inspect_chunks.py 학사경고 --text     # 출처명 대신 본문에서 찾기
    scripts/inspect_chunks.py 기숙사_규정 --full  # 본문 전체 출력(기본은 300자 미리보기)

기본은 '출처명(source)' 검색, --text를 주면 본문에서 찾는다.
리랭커가 특정 문서를 못 잡을 때 그 문서가 실제로 어떻게 쪼개져 저장됐는지
(제목이 다른 청크로 떨어져 나갔는지, 표가 깨졌는지) 확인하는 용도다.
"""
import sys

sys.path.insert(0, ".")

from app.core.Qdrant import qdrant_client
from app.core.config import settings

PREVIEW = 300


def iter_points(collection: str):
    """컬렉션 전체를 페이지 단위로 순회 — 컬렉션이 커져도 누락되지 않게.
    (예전 버전은 limit=2000 한 번만 읽어, 그보다 커지면 조용히 잘렸다)"""
    offset = None
    while True:
        points, offset = qdrant_client.scroll(
            collection_name=collection, limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        if not points:
            return
        yield from points
        if offset is None:
            return


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    by_text = "--text" in argv
    full = "--full" in argv
    if not args:
        print(__doc__)
        return 1

    key = args[0]
    # settings.QDRANT_COLLECTION이 아니라 active_collection을 쓴다 — 하이브리드 토글에 따라
    # 실제 컬렉션이 갈리기 때문(QdrantVectorStore와 같은 기준).
    # 예전 버전은 QDRANT_COLLECTION('school_documents')을 직접 봐서 404가 났다
    # (실제 컬렉션은 'school_documents_hybrid').
    collection = settings.active_collection
    field = "본문" if by_text else "출처명"

    matched, total = [], 0
    for p in iter_points(collection):
        total += 1
        pl = p.payload or {}
        hay = (pl.get("text") or "") if by_text else (pl.get("source") or "")
        if key in hay:
            matched.append(pl)

    matched.sort(key=lambda pl: (str(pl.get("source") or ""), pl.get("chunk_index") or 0))

    print(f"컬렉션 {collection} · 전체 {total}청크")
    print(f"'{key}' {field} 일치 → {len(matched)}청크\n")
    if not matched:
        print("일치하는 청크가 없습니다. --text 옵션으로 본문 검색을 해보세요.")
        return 0

    for pl in matched:
        text = pl.get("text") or ""
        body = text if full else text[:PREVIEW] + ("…" if len(text) > PREVIEW else "")
        print(f"[{pl.get('source')} #{pl.get('chunk_index')}] "
              f"topic={pl.get('topic')} len={len(text)}")
        if pl.get("article"):
            print(f"  article: {pl.get('article')}")
        print(f"  {' '.join(body.split())}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
