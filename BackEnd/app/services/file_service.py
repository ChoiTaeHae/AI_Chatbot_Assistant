"""
파일 서비스 — 다운로드용 파일 관리 비즈니스 로직

documents/{topic}/ 폴더에 파일을 저장·삭제·조회한다.
RAG(Qdrant) 와는 무관하며, 학생에게 제공할 양식/자료를 관리한다.
"""
from pathlib import Path

DOCUMENTS_BASE = Path("documents")

from app.core.topics import TOPICS as TOPIC_LABELS, VALID_TOPICS

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".hwp", ".hwpx",
    ".txt", ".md", ".jpg", ".jpeg", ".png",
}

# ── Topic 캐시 (DB topic 추가 시 갱신 가능) ──────────────────────
_topic_labels: dict[str, str] = dict(TOPIC_LABELS)
_valid_topics: set[str] = set(VALID_TOPICS)


def refresh_topic_cache(labels: dict[str, str]) -> None:
    """admin_service에서 topic 추가/수정/삭제 후 호출해 캐시 갱신."""
    global _topic_labels, _valid_topics
    _topic_labels = dict(labels)
    _valid_topics = set(labels.keys())
    for topic in _valid_topics:
        (DOCUMENTS_BASE / topic).mkdir(parents=True, exist_ok=True)


def is_valid_topic(topic: str) -> bool:
    return topic in _valid_topics


# ── 전역 파일 캐시 ────────────────────────────────────────────
# 서버 시작 시 + 관리자 업로드/삭제 시 갱신.
# school_agent 에서 O(1) 로 "이 topic 에 파일 있냐" 확인에 사용.
AVAILABLE_FILES: dict[str, list[str]] = {}


def refresh_available_files() -> None:
    """documents/ 폴더를 스캔해서 AVAILABLE_FILES 업데이트"""
    global AVAILABLE_FILES
    for topic in _valid_topics:
        folder = DOCUMENTS_BASE / topic
        folder.mkdir(parents=True, exist_ok=True)
        AVAILABLE_FILES[topic] = [
            f.name for f in sorted(folder.iterdir())
            if f.is_file() and not f.name.startswith((".", "_"))
        ]
    total = sum(len(v) for v in AVAILABLE_FILES.values())
    print(f"[FileService] 파일 캐시 갱신 완료 — 총 {total}개")


class FileService:
    """다운로드 파일 관리 서비스"""

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

    # ── 파일 경로 ──────────────────────────────────────────
    def _topic_dir(self, topic: str) -> Path:
        folder = DOCUMENTS_BASE / topic
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _file_path(self, topic: str, filename: str) -> Path:
        return self._topic_dir(topic) / self.safe_filename(filename)

    # ── 비즈니스 로직 ──────────────────────────────────────
    def list_files(self) -> dict:
        result: dict[str, list[dict]] = {}
        for topic in _valid_topics:
            folder = self._topic_dir(topic)
            files = [
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "topic": topic,
                    "label": _topic_labels[topic],
                }
                for f in sorted(folder.iterdir())
                if f.is_file() and not f.name.startswith((".", "_"))
            ]
            result[topic] = files
        return {"files": result, "labels": _topic_labels}

    def save_file(self, topic: str, filename: str, content: bytes) -> dict:
        self.validate_topic(topic)
        self.validate_extension(filename)
        clean_name = self.safe_filename(filename)

        dest = self._file_path(topic, clean_name)
        dest.write_bytes(content)

        refresh_available_files()   # 캐시 갱신

        return {
            "success": True,
            "topic": topic,
            "filename": clean_name,
            "size": len(content),
            "message": f"'{clean_name}' 업로드 완료",
        }

    def delete_file(self, topic: str, filename: str) -> dict:
        self.validate_topic(topic)
        path = self._file_path(topic, filename)

        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")

        path.unlink()
        refresh_available_files()   # 캐시 갱신

        return {
            "success": True,
            "topic": topic,
            "filename": filename,
            "message": f"'{filename}' 삭제 완료",
        }

    def get_file_path(self, topic: str, filename: str) -> Path:
        self.validate_topic(topic)
        path = self._file_path(topic, filename)

        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")

        return path


# 싱글톤 인스턴스
file_service = FileService()
