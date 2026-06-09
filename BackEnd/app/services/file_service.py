"""
파일 서비스 — 다운로드용 파일 관리 비즈니스 로직

documents/{topic}/ 폴더에 파일을 저장·삭제·조회한다.
RAG(Qdrant) 와는 무관하며, 학생에게 제공할 양식/자료를 관리한다.
"""
from pathlib import Path

DOCUMENTS_BASE = Path("documents")

VALID_TOPICS = {"graduation", "schedule", "leave", "campus", "scholarship", "general"}
TOPIC_LABELS = {
    "graduation":  "졸업요건",
    "schedule":    "학사일정",
    "leave":       "휴학/복학",
    "campus":      "캠퍼스/시설",
    "scholarship": "장학금",
    "general":     "일반",
}

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".hwp", ".hwpx",
    ".txt", ".md", ".jpg", ".jpeg", ".png",
}


class FileService:
    """다운로드 파일 관리 서비스"""

    # ── 유효성 검사 ────────────────────────────────────────
    def validate_topic(self, topic: str) -> None:
        if topic not in VALID_TOPICS:
            raise ValueError(f"유효하지 않은 topic: {topic}. 가능한 값: {sorted(VALID_TOPICS)}")

    def validate_extension(self, filename: str) -> None:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"지원하지 않는 확장자: {ext}. 허용: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    def safe_filename(self, filename: str) -> str:
        """경로 탈출(path traversal) 방지 — 파일명만 추출"""
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
        """전체 topic의 파일 목록 반환"""
        result: dict[str, list[dict]] = {}
        for topic in VALID_TOPICS:
            folder = self._topic_dir(topic)
            files = [
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "topic": topic,
                    "label": TOPIC_LABELS[topic],
                }
                for f in sorted(folder.iterdir())
                if f.is_file() and not f.name.startswith((".", "_"))
            ]
            result[topic] = files
        return {"files": result, "labels": TOPIC_LABELS}

    def save_file(self, topic: str, filename: str, content: bytes) -> dict:
        """파일을 documents/{topic}/ 에 저장"""
        self.validate_topic(topic)
        self.validate_extension(filename)
        clean_name = self.safe_filename(filename)

        dest = self._file_path(topic, clean_name)
        dest.write_bytes(content)

        return {
            "success": True,
            "topic": topic,
            "filename": clean_name,
            "size": len(content),
            "message": f"'{clean_name}' 업로드 완료",
        }

    def delete_file(self, topic: str, filename: str) -> dict:
        """파일 삭제"""
        self.validate_topic(topic)
        path = self._file_path(topic, filename)

        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")

        path.unlink()
        return {
            "success": True,
            "topic": topic,
            "filename": filename,
            "message": f"'{filename}' 삭제 완료",
        }

    def get_file_path(self, topic: str, filename: str) -> Path:
        """다운로드용 파일 경로 반환"""
        self.validate_topic(topic)
        path = self._file_path(topic, filename)

        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filename}")

        return path


# 싱글톤 인스턴스
file_service = FileService()
