"""
일회성 마이그레이션: 로컬 documents/{topic}/ 파일을 document_file 테이블로 이관.

공유 DB에 넣으므로 한 명만 실행하면 전원이 공유한다.
이미 같은 (topic, filename)이 있으면 건너뛴다 (중복 삽입 방지).

실행 (BackEnd 폴더에서):
    python -m scripts.migrate_files_to_db
"""
import asyncio
import mimetypes
from pathlib import Path

from sqlalchemy import select

from app.core.Database import AsyncSessionLocal, engine, Base
from app.models.DB_Table import DocumentFile

DOCUMENTS_BASE = Path("documents")
ALLOWED = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".hwp", ".hwpx",
    ".txt", ".md", ".jpg", ".jpeg", ".png",
}


async def main() -> None:
    # 테이블이 없으면 생성 (create_all은 없는 테이블만 만듦 — 이미 있으면 no-op)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if not DOCUMENTS_BASE.exists():
        print(f"[migrate] {DOCUMENTS_BASE} 폴더가 없습니다. 이관할 파일이 없습니다.")
        return

    inserted, skipped = 0, 0
    async with AsyncSessionLocal() as session:
        for topic_dir in sorted(DOCUMENTS_BASE.iterdir()):
            if not topic_dir.is_dir():
                continue
            topic = topic_dir.name
            for f in sorted(topic_dir.iterdir()):
                if not f.is_file() or f.name.startswith((".", "_")):
                    continue
                if f.suffix.lower() not in ALLOWED:
                    continue

                existing = await session.scalar(
                    select(DocumentFile).where(
                        DocumentFile.topic == topic,
                        DocumentFile.filename == f.name,
                    )
                )
                if existing:
                    print(f"  [skip] {topic}/{f.name} (이미 존재)")
                    skipped += 1
                    continue

                content = f.read_bytes()
                ctype, _ = mimetypes.guess_type(f.name)
                session.add(DocumentFile(
                    topic=topic,
                    filename=f.name,
                    content=content,
                    content_type=ctype,
                    size=len(content),
                ))
                print(f"  [ok]   {topic}/{f.name} ({len(content):,} bytes)")
                inserted += 1

        await session.commit()

    print(f"\n[migrate] 완료 — 삽입 {inserted}개, 스킵 {skipped}개")


if __name__ == "__main__":
    asyncio.run(main())
