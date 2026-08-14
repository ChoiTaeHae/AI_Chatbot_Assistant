"""
Admin 서비스 — 관리자 기능 비즈니스 로직

대시보드, 사용 통계, 서비스 설정, 보안/권한, RAG 문서 관리를 담당한다.
각 라우터는 이 서비스를 호출하고 HTTP 변환만 처리한다.
"""
import asyncio
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date, delete

from app.core.config import settings
from app.models.DB_Table import (Student, Department, Course, ChatLog, ChatSession, ChatMessage,
                                 ChatFeedback, Topic, Faq, FaqQuestion)
from app.rag.ingest import ingest_file
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.schemas.admins import (
    FaqCreateRequest,
    FaqUpdateRequest,
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
    DocumentUpdateRequest,
    DocumentUpdateResponse,
    ChunkItem,
    ChunkListResponse,
    ChunkUpdateRequest,
    ChunkUpdateResponse,
    ChatSessionItem,
    ChatSessionListResponse,
    ChatMessageItem,
    ChatSessionDetailResponse,
    FeedbackItem,
    AdminFeedbackRequest,
    TopicItem,
    TopicCreateRequest,
    TopicUpdateRequest,
)

from app.services.file_service import is_valid_topic as _is_valid_topic, refresh_topic_cache, file_service
# 문서 처리 전담 작업자(스레드 풀) 1명 고용
_ingest_executor = ThreadPoolExecutor(max_workers=1)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".txt", ".md", ".hwpx",  # 문서
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",  # 이미지 (OCR 처리)
}
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

        # 주제별 분포 (전체 기간) — DB에서 label 동적 로드
        topic_label_rows = await db.execute(select(Topic.name, Topic.label))
        topic_labels = {row.name: row.label for row in topic_label_rows}
        topic_labels.setdefault("general", "일반")

        # 지금 쓰지 않는 옛 topic은 제외한다.
        #
        # chat_log에는 예전 이름으로 남은 기록이 섞여 있다(실측 12종 216건: cafeteria,
        # facility_usage, Facility_Rental, academic_status, 앞에 공백이 붙은 ' drop_out',
        # 대소문자만 다른 'Cafeteria' 등). 예전에는 라벨을 못 찾으면 intent 문자열을 그대로
        # 썼기 때문에, 한글 라벨 사이에 영문 옛 이름이 그대로 노출됐다.
        #
        # 지우지 않고 걸러만 내는 이유 — chat_log는 실제 사용 기록이라 통계의 근거다.
        # 행을 지우면 '전체 질문 수'가 줄어 다른 지표와 어긋난다. 화면에서만 뺀다.
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
                label=topic_labels[row.intent],
            )
            for row in topic_rows
            if row.intent in topic_labels
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
        """서버가 '지금 실제로' 쓰고 있는 설정을 보여준다(읽기 전용).

        예전에는 .env 값을 그대로 나열해, 화면과 실제 동작이 어긋나는 항목이 둘 있었다.
          · Qdrant 컬렉션: QDRANT_COLLECTION('school_documents')을 보여줬지만 HYBRID_SEARCH가
            켜져 있으면 실제로는 HYBRID_COLLECTION을 쓴다. 관리자가 화면의 이름으로 컬렉션을
            찾으면 없다(실측: 404 Collection doesn't exist). 컬렉션 선택 규칙은
            settings.active_collection 한 곳에만 두고 여기서도 그걸 읽는다(qdrant_store와 동일).
          · 답변 생성 모델: MODEL_PATH(로컬 GGUF)만 보여줘, LLM_PROVIDER=vertex로 돌 때도
            쓰지 않는 파일 경로가 떴다. 무엇이 답변을 만드는지 화면만 봐선 알 수 없었다.
        """
        provider = (settings.LLM_PROVIDER or "local").lower()
        return SettingsResponse(
            dev_mode=settings.DEV_MODE,
            llm_provider=provider,
            # 실제로 답변을 생성하는 모델 — provider에 따라 읽는 값이 다르다.
            llm_model=(settings.GEMINI_MODEL if provider == "vertex" else settings.MODEL_PATH),
            model_path=settings.MODEL_PATH,
            device=settings.DEVICE,
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_device=settings.EMBEDDING_DEVICE,
            qdrant_collection=settings.active_collection,
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

    # ── 채팅 내역 ───────────────────────────────────────────
    async def get_chat_sessions(
        self, db: AsyncSession, search: str = "", page: int = 1, limit: int = 50
    ) -> ChatSessionListResponse:
        base_q = (
            select(
                ChatSession.id,
                ChatSession.started_at,
                ChatSession.last_message_at,
                Student.name.label("student_name"),
                Student.student_no,
            )
            .join(Student, ChatSession.student_id == Student.id)
            .where(ChatSession.is_deleted == False)
            .order_by(ChatSession.last_message_at.desc())
        )
        if search:
            like = f"%{search}%"
            base_q = base_q.where(
                Student.name.ilike(like) | Student.student_no.ilike(like)
            )

        total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar_one()
        rows = (await db.execute(base_q.offset((page - 1) * limit).limit(limit))).all()
        session_ids = [r.id for r in rows]

        msg_rows, first_msgs = {}, {}
        if session_ids:
            msg_q = (
                select(ChatMessage.session_id, func.count(ChatMessage.id).label("cnt"))
                .where(ChatMessage.session_id.in_(session_ids))
                .group_by(ChatMessage.session_id)
            )
            msg_rows = {r.session_id: r for r in (await db.execute(msg_q)).all()}

            min_id_sub = (
                select(ChatMessage.session_id, func.min(ChatMessage.id).label("min_id"))
                .where(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "user")
                .group_by(ChatMessage.session_id)
                .subquery()
            )
            first_msg_q = (
                select(ChatMessage.session_id, ChatMessage.content, ChatMessage.intent)
                .join(min_id_sub, ChatMessage.id == min_id_sub.c.min_id)
            )
            first_msgs = {r.session_id: r for r in (await db.execute(first_msg_q)).all()}

        sessions = []
        for r in rows:
            msg_info = msg_rows.get(r.id)
            first = first_msgs.get(r.id)
            sessions.append(ChatSessionItem(
                id=r.id,
                student_name=r.student_name,
                student_no=r.student_no,
                intent=first.intent if first else None,
                message_count=msg_info.cnt if msg_info else 0,
                first_message=first.content[:80] if first else None,
                started_at=r.started_at,
                last_message_at=r.last_message_at,
            ))
        return ChatSessionListResponse(sessions=sessions, total=total)

    async def get_session_messages(
        self, db: AsyncSession, session_id: int
    ) -> ChatSessionDetailResponse:
        row = (await db.execute(
            select(ChatSession, Student.name, Student.student_no)
            .join(Student, ChatSession.student_id == Student.id)
            .where(ChatSession.id == session_id, ChatSession.is_deleted == False)
        )).first()
        if not row:
            raise LookupError(f"세션을 찾을 수 없습니다. id={session_id}")

        _, student_name, student_no = row
        msgs = (await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )).scalars().all()

        # 메시지별 피드백 한 번에 조회
        msg_ids = [m.id for m in msgs]
        feedbacks: dict[int, ChatFeedback] = {}
        if msg_ids:
            fb_rows = (await db.execute(
                select(ChatFeedback).where(ChatFeedback.message_id.in_(msg_ids))
            )).scalars().all()
            feedbacks = {f.message_id: f for f in fb_rows}

        return ChatSessionDetailResponse(
            session_id=session_id,
            student_name=student_name,
            student_no=student_no,
            messages=[
                ChatMessageItem(
                    id=m.id, role=m.role, content=m.content,
                    intent=m.intent, topic=m.topic,
                    source=m.source, source_file=m.source_file,
                    created_at=m.created_at,
                    feedback=FeedbackItem(
                        id=feedbacks[m.id].id,
                        is_helpful=feedbacks[m.id].is_helpful,
                        rating=feedbacks[m.id].rating,
                        comment=feedbacks[m.id].comment,
                        created_at=feedbacks[m.id].created_at,
                    ) if m.id in feedbacks else None,
                )
                for m in msgs
            ],
        )

    async def upsert_feedback(
        self, db: AsyncSession, message_id: int, req: AdminFeedbackRequest
    ) -> FeedbackItem:
        existing = await db.scalar(
            select(ChatFeedback).where(ChatFeedback.message_id == message_id)
        )
        if existing:
            existing.is_helpful = req.is_helpful
            existing.rating = req.rating
            existing.comment = req.comment
        else:
            existing = ChatFeedback(
                message_id=message_id,
                is_helpful=req.is_helpful,
                rating=req.rating,
                comment=req.comment,
            )
            db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return FeedbackItem(
            id=existing.id,
            is_helpful=existing.is_helpful,
            rating=existing.rating,
            comment=existing.comment,
            created_at=existing.created_at,
        )

    # ── RAG 문서 관리 ───────────────────────────────────────
    def _run_ingest(
        self,
        job_id: str,
        tmp_path: Path,
        source: str,
        filename: str,
        topic: str | None,
        doc_date: str | None = None,
        url: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
    ) -> None:
        """실제 인제스트 실행 — ThreadPool 안에서 호출됨"""
        try:
            self._upload_jobs[job_id]["status"] = "processing"   # 대기표(job_id)별 진행 상황을 기록할 장부
            chunk_count = ingest_file(
                file_path=tmp_path,
                source=source,
                service=rag_service,
                topic=topic,
                doc_date=doc_date,
                url=url,
                contact_name=contact_name,
                contact_phone=contact_phone,
                original_filename=filename,
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
        doc_date: str | None = None,
        url: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
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
        if topic and not _is_valid_topic(topic):
            raise ValueError(f"유효하지 않은 주제: {topic}.")

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
        _ingest_executor.submit(self._run_ingest, job_id, tmp_path, source, filename, topic, doc_date, url, contact_name, contact_phone)
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
        doc_date: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
    ) -> None:
        """URL 크롤링 및 RAG 인제스트 — ThreadPool 안에서 호출됨"""
        from app.rag.Loader.web_crawler import fetch_page_html, parse_notice_page
        from app.rag.Chunking import smart_split
        import re as _re
        try:
            self._upload_jobs[job_id]["status"] = "processing"

            # HTML 한 번만 fetch 후 재사용
            html = fetch_page_html(url)
            page = parse_notice_page(html, url)
            document_text = page.to_document_text()

            # <img> 태그가 있으면 OCR로 이미지 텍스트 추가
            if "<img" in html:
                try:
                    ocr_full = rag_service.ocr_processor.process_html(html, base_url=url)
                    # process_html 결과에서 [이미지 텍스트: ...] 부분만 추출
                    img_texts = _re.findall(r'\[이미지 텍스트: (.+?)\]', ocr_full)
                    if img_texts:
                        document_text += "\n\n[이미지 OCR]\n" + "\n".join(img_texts)
                        print(f"[AdminService] 이미지 OCR {len(img_texts)}건 추가")
                except Exception as ocr_err:
                    print(f"[AdminService] 이미지 OCR 실패 (무시): {ocr_err}")
            raw_chunks = smart_split(document_text, chunk_size=settings.CRAWL_CHUNK_SIZE, embed_fn=rag_service.embedding.embed_texts)
            if not raw_chunks:
                # 텍스트·OCR 모두 실패 시 제목 기반 최소 청크 생성 (URL은 임베딩 제외, payload로만 보존)
                fallback = f"제목: {page.title}"
                if page.author:
                    fallback += f"\n작성자: {page.author}"
                if page.published_at:
                    fallback += f"\n작성일: {page.published_at}"
                raw_chunks = [{"chapter": None, "article": None, "path": "", "text": fallback, "embedding_text": fallback}]
                print(f"[AdminService] 텍스트 추출 실패 → 메타데이터 fallback 청크 사용")
            # 크롤러가 '제목' 감지용으로 넣은 ○ 마커는 청킹(제목+본문 그룹핑)에만 쓰고
            # 저장·임베딩 텍스트에선 제거 → 유사도/답변에 영향 없이 깨끗하게 보존.
            # 줄 맨 앞의 마커만 벗겨, 표의 ○/✕ 같은 실제 내용은 건드리지 않음.
            _mk = _re.compile(r"(?m)^[ \t]*[○▷][ \t]+")
            for c in raw_chunks:
                for _k in ("text", "embedding_text", "path", "chapter", "article"):
                    if isinstance(c.get(_k), str):
                        c[_k] = _mk.sub("", c[_k])
            texts = [c["text"] for c in raw_chunks]
            embedding_texts = [c["embedding_text"] for c in raw_chunks]
            chunk_metas = [{"chapter": c["chapter"], "article": c["article"], "path": c["path"]} for c in raw_chunks]
            # 하이브리드면 dense+sparse 함께 (아니면 기존 dense-only)
            sparse_vectors = None
            if settings.HYBRID_SEARCH:
                embeddings, sparse_vectors = rag_service.embedding.embed_hybrid(embedding_texts)
            else:
                embeddings = rag_service.embedding.embed_texts(embedding_texts)
            meta = page.metadata()
            if doc_date:
                meta["doc_date"] = doc_date
            meta["contact_name"] = contact_name
            meta["contact_phone"] = contact_phone
            rag_service.vector_store.upsert_chunks(
                chunks=texts,
                embeddings=embeddings,
                source=source,
                metadata=meta,
                topic=topic,
                chunk_metas=chunk_metas,
                sparse_vectors=sparse_vectors,
            )
            chunk_count = len(texts)
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
        doc_date: str | None = None,
        contact_name: str | None = None,
        contact_phone: str | None = None,
    ) -> str:
        """URL 크롤링 → ThreadPool 등록 → job_id 반환"""
        if not url.startswith(("http://", "https://")):
            raise ValueError("유효하지 않은 URL 형식입니다.")
        if topic and not _is_valid_topic(topic):
            raise ValueError(f"유효하지 않은 주제: {topic}.")
        job_id = f"crawl_{uuid.uuid4().hex[:8]}"
        self._upload_jobs[job_id] = {
            "status": "queued",
            "source": source,
            "topic": topic,
            "file_name": url,
        }
        _ingest_executor.submit(self._run_crawl, job_id, url, source, topic, doc_date, contact_name, contact_phone)
        return job_id

    def update_document(self, source: str, body: DocumentUpdateRequest) -> DocumentUpdateResponse:
        """문서 메타데이터 수정 — 본문·벡터는 건드리지 않는다.

        보낸 필드만 갱신한다(exclude_unset). 빈 문자열은 '값 비우기'로 보고 None으로 넘겨
        payload에서 키 자체를 지운다 — 화면에서 지운 값이 ''로 남아 '-' 대신 빈칸이 보이는
        일을 막기 위함.
        """
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise ValueError("수정할 항목이 없습니다.")

        topic = fields.get("topic")
        if topic and not _is_valid_topic(topic):
            raise ValueError(f"유효하지 않은 주제: {topic}.")

        normalized = {}
        for key, value in fields.items():
            if isinstance(value, str):
                value = value.strip() or None      # 공백만 입력한 것도 비우기로 취급
            normalized[key] = value

        updated = rag_service.vector_store.update_source_metadata(source, normalized)
        if updated == 0:
            raise LookupError(f"'{source}' 문서를 찾을 수 없습니다.")
        return DocumentUpdateResponse(
            success=True,
            source=source,
            updated_chunks=updated,
            message=f"'{source}' 메타데이터 수정 완료 ({updated}개 청크 갱신, 본문·임베딩 유지)",
        )

    def list_chunks(self, source: str) -> ChunkListResponse:
        """문서가 실제로 어떻게 쪼개져 저장됐는지 조회한다."""
        chunks = rag_service.vector_store.list_chunks(source)
        if not chunks:
            raise LookupError(f"'{source}' 문서를 찾을 수 없습니다.")
        items = [ChunkItem(chars=len(c["text"]), **c) for c in chunks]
        return ChunkListResponse(source=source, chunks=items, total=len(items))

    def update_chunk(self, source: str, chunk_index: int, body: ChunkUpdateRequest) -> ChunkUpdateResponse:
        """청크 본문 수정 — 그 청크의 본문과 벡터를 함께 갱신한다.

        문서 재업로드와 달리 다른 청크는 건드리지 않으므로, 손으로 정리해 둔 청크가
        재청킹으로 흐트러지지 않는다. 대신 임베딩을 다시 계산해야 해서 메타데이터
        수정보다 느리다(BGE-M3 인코딩 1회).
        """
        text = (body.text or "").strip()
        if not text:
            raise ValueError("청크 본문은 비워 둘 수 없습니다.")

        chunk = rag_service.vector_store.get_chunk(source, chunk_index)
        if chunk is None:
            raise LookupError(f"'{source}' 문서의 {chunk_index}번 청크를 찾을 수 없습니다.")
        if text == chunk["text"]:
            # 내용이 같은데 재임베딩하는 건 수 초를 그냥 버리는 일이라 여기서 끊는다
            return ChunkUpdateResponse(
                success=True, source=source, chunk_index=chunk_index,
                chars=len(text), message="변경된 내용이 없습니다.",
            )

        # 인제스트와 같은 규칙으로 임베딩 텍스트를 만든다(chunker._make_chunk와 동일).
        # 여기서 규칙이 어긋나면 이 청크만 다른 기준으로 임베딩돼 검색 순위가 틀어진다.
        path = chunk.get("path") or ""
        embedding_text = f"{path}\n{text}" if path else text

        sparse_vector = None
        if settings.HYBRID_SEARCH:
            embeddings, sparse_vectors = rag_service.embedding.embed_hybrid([embedding_text])
            sparse_vector = sparse_vectors[0]
        else:
            embeddings = rag_service.embedding.embed_texts([embedding_text])

        rag_service.vector_store.update_chunk_text(
            point_id=chunk["point_id"],
            text=text,
            embedding=embeddings[0],
            sparse_vector=sparse_vector,
        )
        print(f"[AdminService] 청크 수정: {source}#{chunk_index} "
              f"({len(chunk['text'])}자 → {len(text)}자, 재임베딩 완료)")
        return ChunkUpdateResponse(
            success=True,
            source=source,
            chunk_index=chunk_index,
            chars=len(text),
            message=f"{chunk_index}번 청크 수정 완료 ({len(chunk['text'])}자 → {len(text)}자, 재임베딩 반영)",
        )

    def delete_document(self, source: str) -> DocumentDeleteResponse:
        deleted = rag_service.vector_store.delete_by_source(source)
        if deleted == 0:
            raise LookupError(f"'{source}' 문서를 찾을 수 없습니다.")
        return DocumentDeleteResponse(
            success=True,
            source=source,
            message=f"'{source}' 문서 삭제 완료 ({deleted}개 청크 삭제)",
        )

    # ── Topic CRUD ────────────────────────────────────────────────

    async def list_topics(self, db: AsyncSession) -> list[Topic]:
        result = await db.execute(select(Topic).order_by(Topic.id))
        return result.scalars().all()

    _VALID_HANDLER_TYPES = {"rag", "campus", "graduation", "scholarship", "schedule",
                            "general", "dining", "my_grades"}

    async def create_topic(self, db: AsyncSession, body: TopicCreateRequest) -> Topic:
        # 이름·라벨 앞뒤 공백 제거 — ' graduate_school'처럼 공백 낀 채 저장돼 topic 매칭이
        # 깨지는 것을 방지 (중복 체크·저장 모두 정리된 값 사용)
        name = (body.name or "").strip()
        label = body.label.strip() if isinstance(body.label, str) else body.label
        if not name:
            raise ValueError("topic 이름은 비어 있을 수 없습니다.")
        if body.handler_type not in self._VALID_HANDLER_TYPES:
            raise ValueError(
                f"유효하지 않은 handler_type: {body.handler_type}. "
                f"가능한 값: {sorted(self._VALID_HANDLER_TYPES)}"
            )
        existing = await db.execute(select(Topic).where(Topic.name == name))
        if existing.scalar_one_or_none():
            raise ValueError(f"이미 존재하는 topic: {name}")
        topic = Topic(
            name=name,
            label=label,
            handler_type=body.handler_type,
            sentences=body.sentences,
            description=body.description,
            is_system=False,
            is_active=True,
        )
        db.add(topic)
        await db.commit()
        await db.refresh(topic)
        await self._reload_topic_router(db)
        return topic

    async def update_topic(self, db: AsyncSession, name: str, body: TopicUpdateRequest) -> Topic:
        result = await db.execute(select(Topic).where(Topic.name == name))
        topic = result.scalar_one_or_none()
        if not topic:
            raise LookupError("topic을 찾을 수 없습니다.")
        if body.label is not None:
            topic.label = body.label.strip() if isinstance(body.label, str) else body.label
        if body.sentences is not None:
            topic.sentences = body.sentences
        if body.description is not None:
            topic.description = body.description
        if body.is_active is not None:
            topic.is_active = body.is_active
        await db.commit()
        await db.refresh(topic)
        await self._reload_topic_router(db)
        return topic

    async def delete_topic(self, db: AsyncSession, name: str) -> None:
        result = await db.execute(select(Topic).where(Topic.name == name))
        topic = result.scalar_one_or_none()
        if not topic:
            raise LookupError("topic을 찾을 수 없습니다.")
        if topic.is_system:
            raise ValueError("시스템 topic은 삭제할 수 없습니다.")
        chunk_count = rag_service.vector_store.count_by_topic(name)
        if chunk_count > 0:
            raise ValueError(
                f"topic '{name}'에 RAG 문서 {chunk_count}개가 등록되어 있습니다. "
                f"문서를 먼저 삭제한 후 topic을 삭제하세요."
            )
        file_count = len((await file_service.list_files())["files"].get(name, []))
        if file_count > 0:
            raise ValueError(
                f"topic '{name}'에 다운로드 파일 {file_count}개가 있습니다. "
                f"파일을 먼저 삭제한 후 topic을 삭제하세요."
            )
        await db.delete(topic)
        await db.commit()
        await self._reload_topic_router(db)

    async def _reload_topic_router(self, db: AsyncSession) -> None:
        """topic 변경 후 TopicRouter + FileService 캐시 즉시 갱신."""
        from app.agents.topic_router import topic_router
        result = await db.execute(select(Topic).where(Topic.is_active == True))
        topics = result.scalars().all()
        topic_data = [
            {"name": t.name, "label": t.label,
             "handler_type": t.handler_type, "sentences": t.sentences or []}
            for t in topics
        ]
        labels = {t.name: t.label for t in topics}
        refresh_topic_cache(labels)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, topic_router.reload, topic_data)

    # ── FAQ CRUD ───────────────────────────────────────────────────
    # 모든 변경 뒤에 _reload_faq_index()를 호출한다. FAQ 매칭은 메모리 인덱스(질문 임베딩)로만
    # 이뤄지므로, 재적재하지 않으면 표를 고쳐도 옛 답변이 계속 나간다. topic이 저장 시점에
    # 라우터를 다시 올리는 것과 같은 이유·같은 방식이다.

    async def list_faqs(self, db: AsyncSession) -> list[dict]:
        faqs = (await db.execute(select(Faq).order_by(Faq.id))).scalars().all()
        qrows = (await db.execute(
            select(FaqQuestion).order_by(FaqQuestion.faq_id, FaqQuestion.id))).scalars().all()
        by_faq: dict[int, list] = {}
        for q in qrows:
            by_faq.setdefault(q.faq_id, []).append(
                {"id": q.id, "text": q.text, "enabled": q.enabled})
        return [{"id": f.id, "answer": f.answer, "category": f.category, "enabled": f.enabled,
                 "created_at": f.created_at, "questions": by_faq.get(f.id, [])} for f in faqs]

    async def create_faq(self, db: AsyncSession, body: FaqCreateRequest) -> dict:
        answer = (body.answer or "").strip()
        if not answer:
            raise ValueError("답변을 입력하세요.")
        faq = Faq(answer=answer, category=(body.category or None), enabled=True)
        db.add(faq)
        await db.flush()                      # id 확보 후 질문 변형 연결
        for text in self._clean_questions(body.questions):
            db.add(FaqQuestion(faq_id=faq.id, text=text, enabled=True))
        await db.commit()
        await self._reload_faq_index()
        return await self._get_faq(db, faq.id)

    async def update_faq(self, db: AsyncSession, faq_id: int, body: FaqUpdateRequest) -> dict:
        faq = await self._get_faq_row(db, faq_id)
        if body.answer is not None:
            answer = body.answer.strip()
            if not answer:
                raise ValueError("답변은 비울 수 없습니다.")
            faq.answer = answer
        if body.category is not None:
            faq.category = body.category.strip() or None
        if body.enabled is not None:
            faq.enabled = body.enabled
        if body.questions is not None:
            # 목록 통째 교체 — 기존 행을 지우고 다시 넣는다(부분 대조보다 단순하고 안전)
            await db.execute(delete(FaqQuestion).where(FaqQuestion.faq_id == faq_id))
            for text in self._clean_questions(body.questions):
                db.add(FaqQuestion(faq_id=faq_id, text=text, enabled=True))
        await db.commit()
        await self._reload_faq_index()
        return await self._get_faq(db, faq_id)

    async def delete_faq(self, db: AsyncSession, faq_id: int) -> None:
        faq = await self._get_faq_row(db, faq_id)
        await db.delete(faq)               # faq_question은 ondelete=CASCADE로 함께 삭제
        await db.commit()
        await self._reload_faq_index()

    async def _get_faq_row(self, db: AsyncSession, faq_id: int) -> Faq:
        faq = (await db.execute(select(Faq).where(Faq.id == faq_id))).scalar_one_or_none()
        if not faq:
            raise LookupError("FAQ를 찾을 수 없습니다.")
        return faq

    async def _get_faq(self, db: AsyncSession, faq_id: int) -> dict:
        faq = await self._get_faq_row(db, faq_id)
        qrows = (await db.execute(
            select(FaqQuestion).where(FaqQuestion.faq_id == faq_id)
            .order_by(FaqQuestion.id))).scalars().all()
        return {"id": faq.id, "answer": faq.answer, "category": faq.category,
                "enabled": faq.enabled, "created_at": faq.created_at,
                "questions": [{"id": q.id, "text": q.text, "enabled": q.enabled} for q in qrows]}

    @staticmethod
    def _clean_questions(items: list[str] | None) -> list[str]:
        """공백 제거 + 빈 줄 제거 + 중복 제거(입력 순서 유지)."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in items or []:
            text = (raw or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out

    @staticmethod
    async def _reload_faq_index() -> int:
        """FAQ 메모리 인덱스 재적재. 실패해도 저장 자체는 되돌리지 않는다
        (DB는 이미 갱신됐고, 최악의 경우 재시작으로 반영되므로 저장을 막을 이유가 없다)."""
        from app.services import faq_index
        try:
            await faq_index.warmup()
        except Exception as e:
            print(f"[Admin] FAQ 인덱스 재적재 실패(저장은 완료됨): {e}")
            return -1
        return len(faq_index._index)


# 싱글톤 인스턴스
admin_service = AdminService()
