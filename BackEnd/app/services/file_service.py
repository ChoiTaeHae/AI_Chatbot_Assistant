"""
파일 서비스 — 다운로드용 파일 관리 비즈니스 로직 (DB 저장)

document_file 테이블에 파일 바이트를 저장·삭제·조회한다.
공유 DB에 저장하므로 한 명이 업로드하면 전원이 공유한다.
RAG(Qdrant) 와는 무관하며, 학생에게 제공할 양식/자료를 관리한다.
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import DocumentFile

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".hwpx",
    ".txt", ".md", ".jpg", ".jpeg", ".png",
}

# ── Topic 캐시 — 서버 시작 시 DB에서 refresh_topic_cache()로 채워짐 ──
_topic_labels: dict[str, str] = {}
_valid_topics: set[str] = set()


def refresh_topic_cache(labels: dict[str, str]) -> None:
    """admin_service에서 topic 추가/수정/삭제 후 호출해 캐시 갱신."""
    global _topic_labels, _valid_topics
    _topic_labels = dict(labels)
    _valid_topics = set(labels.keys())


def is_valid_topic(topic: str) -> bool:
    return topic in _valid_topics


# ── 전역 파일 캐시 ────────────────────────────────────────────
# 서버 시작 시 + 관리자 업로드/삭제 시 갱신.
# school_agent 에서 O(1) 로 "이 topic 에 파일 있냐" 확인에 사용.
# ⚠️ 다른 모듈이 `from ... import AVAILABLE_FILES`로 참조하므로, 재갱신 시
#    새 dict를 대입하지 말고 clear()+update()로 "같은 객체"를 유지해야 한다.
AVAILABLE_FILES: dict[str, list[str]] = {}


async def refresh_available_files() -> None:
    """document_file 테이블을 스캔해서 AVAILABLE_FILES 업데이트"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DocumentFile.topic, DocumentFile.filename).order_by(DocumentFile.filename)
        )
        rows = result.all()

    new_files: dict[str, list[str]] = {topic: [] for topic in _valid_topics}
    for topic, filename in rows:
        new_files.setdefault(topic, []).append(filename)

    # 같은 dict 객체를 유지 (import한 참조가 계속 유효하도록)
    AVAILABLE_FILES.clear()
    AVAILABLE_FILES.update(new_files)

    total = sum(len(v) for v in AVAILABLE_FILES.values())
    print(f"[FileService] 파일 캐시 갱신 완료 — 총 {total}개")


class FileService:
    """다운로드 파일 관리 서비스 (DB 저장)"""

    # ── 유효성 검사 ────────────────────────────────────────
    def validate_topic(self, topic: str) -> None:
        if topic not in _valid_topics:
            raise ValueError(f"유효하지 않은 topic: {topic}. 가능한 값: {sorted(_valid_topics)}")

    def validate_extension(self, filename: str) -> None:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"지원하지 않는 확장자: {ext}. 허용: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    def safe_filename(self, filename: str) -> str:
        name = Path(filename).name
        if not name or name.startswith("."):
            raise ValueError("유효하지 않은 파일명")
        return name

    # ── 비즈니스 로직 ──────────────────────────────────────
    async def list_files(self) -> dict:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DocumentFile.topic, DocumentFile.filename, DocumentFile.size)
                .order_by(DocumentFile.filename)
            )
            rows = result.all()

        files: dict[str, list[dict]] = {topic: [] for topic in _valid_topics}
        for topic, filename, size in rows:
            files.setdefault(topic, []).append({
                "name": filename,
                "size": size,
                "topic": topic,
                "label": _topic_labels.get(topic, topic),
            })
        return {"files": files, "labels": _topic_labels}

    async def save_file(self, topic: str, filename: str, content: bytes, content_type: str | None = None) -> dict:
        self.validate_topic(topic)
        self.validate_extension(filename)
        clean_name = self.safe_filename(filename)

        # PostgreSQL upsert — (topic, filename) 충돌 시 원자적으로 교체.
        # check-then-act 경쟁(동시에 같은 파일 업로드 시 IntegrityError)을 방지한다.
        stmt = pg_insert(DocumentFile).values(
            topic=topic,
            filename=clean_name,
            content=content,
            content_type=content_type,
            size=len(content),
        ).on_conflict_do_update(
            index_elements=[DocumentFile.topic, DocumentFile.filename],
            set_={
                "content": content,
                "content_type": content_type,
                "size": len(content),
            },
        )
        async with AsyncSessionLocal() as session:
            await session.execute(stmt)
            await session.commit()

        await refresh_available_files()   # 캐시 갱신

        return {
            "success": True,
            "topic": topic,
            "filename": clean_name,
            "size": len(content),
            "message": f"'{clean_name}' 업로드 완료",
        }

    async def delete_file(self, topic: str, filename: str) -> dict:
        self.validate_topic(topic)
        clean_name = self.safe_filename(filename)

        async with AsyncSessionLocal() as session:
            existing = await session.scalar(
                select(DocumentFile).where(
                    DocumentFile.topic == topic,
                    DocumentFile.filename == clean_name,
                )
            )
            if not existing:
                raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")
            await session.delete(existing)
            await session.commit()

        await refresh_available_files()   # 캐시 갱신

        return {
            "success": True,
            "topic": topic,
            "filename": clean_name,
            "message": f"'{clean_name}' 삭제 완료",
        }

    async def get_file(self, topic: str, filename: str) -> tuple[bytes, str]:
        """파일 바이트와 파일명을 반환. (다운로드용)"""
        self.validate_topic(topic)
        clean_name = self.safe_filename(filename)

        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(DocumentFile).where(
                    DocumentFile.topic == topic,
                    DocumentFile.filename == clean_name,
                )
            )
        if not row:
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")
        return row.content, clean_name


# 싱글톤 인스턴스
file_service = FileService()
