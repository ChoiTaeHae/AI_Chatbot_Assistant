"""
Admin 서비스 — 관리자 기능 비즈니스 로직

대시보드, 사용 통계, 서비스 설정, 보안/권한, RAG 문서 관리를 담당한다.
각 라우터는 이 서비스를 호출하고 HTTP 변환만 처리한다.
"""
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date

from app.core.config import settings
from app.models.DB_Table import Student, Department, Course, ChatLog
from app.rag.ingest import ingest_file
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.schemas.admins import (
    ChatStatsResponse,
    DailyCount,
    DashboardResponse,
    StatsResponse,
    SettingsResponse,
    TopicCount,
    UserItem,
    UserListResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentDeleteResponse,
)

from app.core.topics import VALID_TOPICS
# 문서 처리 전담 작업자(스레드 풀) 1명 고용
_ingest_executor = ThreadPoolExecutor(max_workers=1)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
VALID_ROLES         = {"student", "admin"}


class AdminService:

    def __init__(self):
        self._upload_jobs: dict[str, dict] = {}

    # ── 대시보드 ────────────────────────────────────────────
    def get_dashboard(self) -> DashboardResponse:
        try:
            sources     = rag_service.vector_store.list_sources()
            total_docs   = len(sources)
            total_chunks = sum(s["chunks"] for s in sources)
        except Exception as e:
            print(f"[AdminService] Qdrant 조회 실패: {e}")
            total_docs = total_chunks = 0

        model_loaded = (llm_service.model is not None) or settings.DEV_MODE
        return DashboardResponse(
            total_documents=total_docs,
            total_chunks=total_chunks,
            model_status="loaded" if model_loaded else "not_loaded",
            dev_mode=settings.DEV_MODE,
            model_path=settings.MODEL_PATH,
        )

    # ── 사용 통계 ───────────────────────────────────────────
    async def get_stats(self, db: AsyncSession) -> StatsResponse:
        student_count = await db.scalar(select(func.count(Student.id)))
        dept_count    = await db.scalar(select(func.count(Department.id)))
        course_count  = await db.scalar(select(func.count(Course.code)))
        admin_count   = await db.scalar(
            select(func.count(Student.id)).where(Student.role == "admin")
        )
        return StatsResponse(
            total_students=student_count or 0,
            total_departments=dept_count or 0,
            total_courses=course_count or 0,
            total_admins=admin_count or 0,
        )

    # ── 채팅 통계 ───────────────────────────────────────────
    async def get_chat_stats(self, db: AsyncSession) -> ChatStatsResponse:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        total_chats = await db.scalar(select(func.count(ChatLog.id))) or 0
        today_chats = await db.scalar(
            select(func.count(ChatLog.id)).where(ChatLog.created_at >= today_start)
        ) or 0
        active_students_7d = await db.scalar(
            select(func.count(func.distinct(ChatLog.student_id)))
            .where(ChatLog.created_at >= week_ago, ChatLog.student_id.isnot(None))
        ) or 0

        # 최근 7일 일별 질문 수
        daily_rows = await db.execute(
            select(
                cast(ChatLog.created_at, Date).label("day"),
                func.count(ChatLog.id).label("cnt"),
            )
            .where(ChatLog.created_at >= week_ago)
            .group_by("day")
            .order_by("day")
        )
        daily_map = {str(row.day): row.cnt for row in daily_rows}
        daily_counts = []
        for i in range(6, -1, -1):
            d = (now - timedelta(days=i)).date()
            daily_counts.append(DailyCount(date=d.strftime("%m-%d"), count=daily_map.get(str(d), 0)))

        # 주제별 분포 (전체 기간)
        topic_labels = {
            "campus":              "캠퍼스",
            "graduation":          "졸업요건",
            "leave":               "휴학/복학",
            "scholarship":         "장학금",
            "dormitory":           "기숙사",
            "course_registration": "수강신청",
            "special_credit":      "특별학점",
            "grades":              "성적",
            "school_rules":        "학칙/규정",
            "general":             "일반",
        }
        topic_rows = await db.execute(
            select(ChatLog.intent, func.count(ChatLog.id).label("cnt"))
            .where(ChatLog.intent.isnot(None))
            .group_by(ChatLog.intent)
            .order_by(func.count(ChatLog.id).desc())
        )
        topic_counts = [
            TopicCount(
                intent=row.intent,
                count=row.cnt,
                label=topic_labels.get(row.intent, row.intent),
            )
            for row in topic_rows
        ]

        return ChatStatsResponse(
            total_chats=total_chats,
            today_chats=today_chats,
            active_students_7d=active_students_7d,
            daily_counts=daily_counts,
            topic_counts=topic_counts,
        )

    # ── 서비스 설정 ─────────────────────────────────────────
    def get_settings(self) -> SettingsResponse:
        return SettingsResponse(
            dev_mode=settings.DEV_MODE,
            model_path=settings.MODEL_PATH,
            device=settings.DEVICE,
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_device=settings.EMBEDDING_DEVICE,
            qdrant_collection=settings.QDRANT_COLLECTION,
            rag_top_k=settings.RAG_TOP_K,
        )

    # ── 보안 / 권한 ─────────────────────────────────────────
    async def get_users(self, db: AsyncSession) -> UserListResponse:
        result = await db.execute(
            select(Student, Department.name)
            .outerjoin(Department, Student.dept_id == Department.id)
        )
        users = [
            UserItem(
                id=s.id,
                student_no=s.student_no,
                name=s.name,
                role=s.role,
                department=dept_name or "-",
            )
            for s, dept_name in result.all()
        ]
        return UserListResponse(users=users, total=len(users))

    async def update_user_role(
        self, db: AsyncSession, user_id: int, role: str
    ) -> UserItem:
        if role not in VALID_ROLES:
            raise ValueError("role은 'student' 또는 'admin'만 가능합니다.")

        result = await db.execute(
            select(Student, Department.name)
            .outerjoin(Department, Student.dept_id == Department.id)
            .where(Student.id == user_id)
        )
        row = result.first()
        if not row:
            raise LookupError(f"사용자를 찾을 수 없습니다. id={user_id}")

        student, dept_name = row
        student.role = role
        await db.commit()
        await db.refresh(student)

        return UserItem(
            id=student.id,
            student_no=student.student_no,
            name=student.name,
            role=student.role,
            department=dept_name or "-",
        )

    # ── RAG 문서 관리 ───────────────────────────────────────
    def _run_ingest(
        self,
        job_id: str,
        tmp_path: Path,
        source: str,
        filename: str,
        topic: str | None,
    ) -> None:
        """실제 인제스트 실행 — ThreadPool 안에서 호출됨"""
        try:
            self._upload_jobs[job_id]["status"] = "processing"   # 대기표(job_id)별 진행 상황을 기록할 장부
            chunk_count = ingest_file(
                file_path=tmp_path,
                source=source,
                service=rag_service,
                topic=topic,
            )
            if chunk_count == 0:
                self._upload_jobs[job_id] = {
                    "status": "error",
                    "message": "문서에서 텍스트를 추출할 수 없습니다.",
                }
            else:
                self._upload_jobs[job_id] = {
                    "status": "done",
                    "source": source,
                    "file_name": filename,
                    "chunks": chunk_count,
                    "message": f"'{filename}' 처리 완료 ({chunk_count}개 청크 생성)",
                }
            print(f"[AdminService] 인제스트 완료: {source} ({chunk_count} chunks)")
        except Exception as e:
            self._upload_jobs[job_id] = {"status": "error", "message": str(e)}
            print(f"[AdminService] 인제스트 오류: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)

    def submit_ingest(
        self,
        file_content: bytes,
        filename: str,
        source: str,
        topic: str | None,
    ) -> str:
        """
        임시 파일 저장 → ThreadPool 인제스트 등록 → job_id 반환.
        라우터가 await file.read() 로 읽은 bytes 를 전달한다.
        """
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"지원하지 않는 파일 형식: {suffix}. "
                f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}"
            )
        if topic and topic not in VALID_TOPICS:
            raise ValueError(
                f"유효하지 않은 주제: {topic}. "
                f"가능한 값: {', '.join(sorted(VALID_TOPICS))}"
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = Path(tmp.name)

        job_id = f"{source}_{tmp_path.stem}"
        self._upload_jobs[job_id] = {
            "status": "queued",
            "source": source,
            "topic": topic,
            "file_name": filename,
        }
        _ingest_executor.submit(self._run_ingest, job_id, tmp_path, source, filename, topic)
        return job_id

    def get_job_status(self, job_id: str) -> dict:
        job = self._upload_jobs.get(job_id)
        if not job:
            raise LookupError(f"작업을 찾을 수 없습니다: {job_id}")
        return job

    def list_documents(self) -> DocumentListResponse:
        try:
            sources = rag_service.vector_store.list_sources()
            items = [DocumentListItem(**s) for s in sources]
            return DocumentListResponse(documents=items, total=len(items))
        except Exception as e:
            print(f"[AdminService] list_documents 오류: {e}")
            raise

    def _run_crawl(
        self,
        job_id: str,
        url: str,
        source: str,
        topic: str | None,
    ) -> None:
        """URL 크롤링 및 RAG 인제스트 — ThreadPool 안에서 호출됨"""
        from app.imsi.crawler import crawl_notice_page
        from app.rag.Chunking import split_by_length
        try:
            self._upload_jobs[job_id]["status"] = "processing"
            page = crawl_notice_page(url)
            document_text = page.to_document_text()
            chunks = split_by_length(document_text, chunk_size=800, overlap=120)
            if not chunks:
                self._upload_jobs[job_id] = {
                    "status": "error",
                    "message": "크롤링한 페이지에서 텍스트를 추출할 수 없습니다.",
                }
                return
            embeddings = rag_service.embedding.embed_texts(chunks)
            rag_service.vector_store.upsert_chunks(
                chunks=chunks,
                embeddings=embeddings,
                source=source,
                metadata=page.metadata(),
                topic=topic,
            )
            chunk_count = len(chunks)
            self._upload_jobs[job_id] = {
                "status": "done",
                "source": source,
                "file_name": url,
                "chunks": chunk_count,
                "message": f"'{page.title}' 크롤링 완료 ({chunk_count}개 청크 생성)",
            }
            print(f"[AdminService] 크롤링 완료: {source} ({chunk_count} chunks)")
        except Exception as e:
            self._upload_jobs[job_id] = {"status": "error", "message": str(e)}
            print(f"[AdminService] 크롤링 오류: {e}")

    def submit_crawl(
        self,
        url: str,
        source: str,
        topic: str | None,
    ) -> str:
        """URL 크롤링 → ThreadPool 등록 → job_id 반환"""
        if not url.startswith(("http://", "https://")):
            raise ValueError("유효하지 않은 URL 형식입니다.")
        if topic and topic not in VALID_TOPICS:
            raise ValueError(
                f"유효하지 않은 주제: {topic}. "
                f"가능한 값: {', '.join(sorted(VALID_TOPICS))}"
            )
        job_id = f"crawl_{uuid.uuid4().hex[:8]}"
        self._upload_jobs[job_id] = {
            "status": "queued",
            "source": source,
            "topic": topic,
            "file_name": url,
        }
        _ingest_executor.submit(self._run_crawl, job_id, url, source, topic)
        return job_id

    def delete_document(self, source: str) -> DocumentDeleteResponse:
        deleted = rag_service.vector_store.delete_by_source(source)
        if deleted == 0:
            raise LookupError(f"'{source}' 문서를 찾을 수 없습니다.")
        return DocumentDeleteResponse(
            success=True,
            source=source,
            message=f"'{source}' 문서 삭제 완료 ({deleted}개 청크 삭제)",
        )


# 싱글톤 인스턴스
admin_service = AdminService()
