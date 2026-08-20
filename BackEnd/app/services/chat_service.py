from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import ChatFeedback, ChatMessage, ChatSession, RewriteLabel, Student
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest, RewriteFeedbackRequest

# 답을 못 찾았을 때 답변 끝에 덧붙이는 안내. 화면 언어별 고정 문장이라 번역을 태우지 않는다
# (번역을 거치면 표현이 매번 달라지는데, 이건 학생에게 하는 약속이라 흔들리면 안 된다).
#
# '등록했다'가 아니라 '전달했다'로 쓴 이유 — 관리자가 제외(ignored)하거나 LLM 선별이
# 학사 무관으로 걸러 내면 답변이 오지 않을 수 있다. 모든 질문에 반드시 답이 온다고 읽히면
# 지키지 못하는 약속이 된다.
#
# 세 언어가 같은 구분자로 시작한다 — 나중에 이 문구만 떼어 낼 때 언어를 몰라도 되게 하려고
# 일부러 맞춘 것이다(_strip_faq_notice).
_FAQ_NOTICE_MARK = "\n\n---\n\n📬 "
_FAQ_PENDING_NOTICE = {
    "ko": _FAQ_NOTICE_MARK + "이 질문을 담당자에게 전달했어요. 답변이 등록되면 알림으로 알려드릴게요.",
    "en": _FAQ_NOTICE_MARK + "I've forwarded this question to our staff. You'll get a notification once an answer is posted.",
    "zh": _FAQ_NOTICE_MARK + "已将此问题转交给负责老师。答复登记后会通过通知告知您。",
}

# 게스트용 — 담당자 전달도, 알림도 약속하지 않는다. 둘 다 학번이 있어야 성립하기 때문이다.
# 대신 로그인하면 무엇이 달라지는지만 알려 준다(막다른 길로 끝내지 않는다).
_FAQ_GUEST_HINT = {
    "ko": _FAQ_NOTICE_MARK + "로그인하시면 이런 질문을 담당자에게 전달하고, 답변이 등록될 때 알림으로 알려드려요.",
    "en": _FAQ_NOTICE_MARK + "Sign in and we'll forward questions like this to our staff, then notify you when an answer is posted.",
    "zh": _FAQ_NOTICE_MARK + "登录后可将此类问题转交给负责老师，答复登记后会通过通知告知您。",
}


def _strip_faq_notice(content: str) -> str:
    """저장된 답변에서 FAQ 접수 안내를 떼어 낸다(멀티턴 맥락으로 넘기기 전에 호출).

    안내가 없으면 원문 그대로 돌려준다. 구분자를 그냥 자르기만 하면 되는 이유는
    이 문구가 항상 답변 맨 끝에만 붙기 때문이다.
    """
    idx = (content or "").find(_FAQ_NOTICE_MARK)
    return content if idx == -1 else content[:idx]


class ChatService:
    async def create_chat_response(
        self,
        request: ChatRequest,
        db: AsyncSession,
        current_user: Student | None,
    ) -> ChatResponse:
        """current_user=None 이면 게스트(비로그인).

        게스트는 대화를 저장하지 않는다 — chat_session·chat_message가 student_id를 필수로
        받기도 하지만, 그보다 로그인하지 않은 사람의 대화를 남길 이유가 없다. 대신 멀티턴
        맥락은 프론트가 직전 1턴을 요청에 실어 보내는 것으로 잇는다.
        개인 데이터가 필요한 질문(성적·졸업요건·장학금 설문)은 각 핸들러가 로그인 안내로 돌려준다.
        """
        is_guest = current_user is None
        student_id = None if is_guest else current_user.id
        session = None

        if not is_guest:
            if request.session_id:
                session = await db.get(ChatSession, request.session_id)
                if session and session.student_id != current_user.id:
                    raise PermissionError("해당 세션에 접근할 수 없습니다.")
                if not session:
                    session = None

            if not request.session_id or session is None:
                session = ChatSession(
                    student_id=current_user.id,
                    title=request.question[:100],
                )
                db.add(session)

            await db.flush()

        # 파일 제안 '예/아니오' 버튼은 대화가 아니라 버튼 동작이다. 이 턴을 대화 메시지로
        # 저장하면 '네'가 다음 질문의 '이전 질문'이 되어 검색어 재작성을 오염시킨다
        # (예: '신청 가능해?' + 이전 '네' → '신청 방법'으로 변질). 파일 전송은 요청 파라미터
        # (pending_file/file_confirm)로 처리되어 DB 기록이 필요 없으므로 이 턴은 저장하지 않는다.
        # 프론트도 같은 이유로 사용자 말풍선을 만들지 않는다(useChat.js confirmFile).
        if request.pending_file and request.file_confirm is not None and not request.pending_context:
            from app.agents.agent_graph import agent_graph
            result = await agent_graph.run(
                question=request.question,
                student_id=student_id,
                db=db,
                pending_file=request.pending_file,
                pending_context=request.pending_context,
                prev_context=None,
                file_confirm=request.file_confirm,
            )
            if not is_guest:
                await db.commit()   # 세션 생성분만 커밋 (메시지는 저장 안 함)
            from app.services.translation_service import translate_answer
            return ChatResponse(
                answer=await translate_answer(result.answer, request.lang),
                session_id=session.id if session else None,
                message_id=None,
                file_offer=result.file_offer,
                file_download=result.file_download,
                map_card=result.map_card,
                dept_card=result.dept_card,
                scholarship_card=getattr(result, "scholarship_card", None),
                weather_card=getattr(result, "weather_card", None),
                pending_context=result.pending_context,
            )

        user_msg = None
        if not is_guest:
            user_msg = ChatMessage(
                session_id=session.id,
                student_id=current_user.id,
                role="user",
                content=request.question,
            )
            db.add(user_msg)
            await db.flush()

        # 이전 대화 1세트 조회 (멀티턴 맥락 유지용)
        # 잡담(topic=general)은 건너뛰고 그 이전의 진짜 주제를 찾는다 — "안녕" 한마디로
        # 진행 중이던 RAG 대화 맥락(예: 휴학)이 끊기는 것을 방지 (잡담을 "투명하게" 취급)
        MAX_PREV_LENGTH = 200
        MAX_LOOKBACK = 20
        prev_context = None

        # 게스트는 저장된 대화가 없으므로 프론트가 보낸 직전 1턴을 그대로 쓴다.
        # 로그인 사용자에게는 이 값을 절대 쓰지 않는다 — DB 기록이 더 정확하고,
        # 클라이언트가 보낸 값으로 맥락을 덮어쓰게 두면 남의 맥락을 주입할 수 있다.
        if is_guest:
            # 길이는 여기서 자른다. 스키마에서 막지 않는 이유는 위 주석 참고
            # (긴 답변 하나로 질문 전체가 422로 실패하는 것을 막기 위해).
            _ptopic = (request.prev_topic or "")[:50]
            if request.prev_question and _ptopic and _ptopic != "general":
                prev_context = {
                    "prev_question": request.prev_question[:MAX_PREV_LENGTH],
                    "prev_answer": _strip_faq_notice(request.prev_answer or "")[:MAX_PREV_LENGTH],
                    "prev_topic": _ptopic,
                }
            recent_msgs = []
        else:
            recent_msgs = (await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id, ChatMessage.id != user_msg.id)
                .order_by(ChatMessage.id.desc())
                .limit(MAX_LOOKBACK)
            )).scalars().all()

        for i, msg in enumerate(recent_msgs):
            if msg.role == "assistant" and msg.topic and msg.topic != "general":
                prev_answer = msg
                prev_question = next(
                    (m for m in recent_msgs[i + 1:] if m.role == "user"), None
                )
                if prev_question:
                    prev_context = {
                        "prev_question": prev_question.content[:MAX_PREV_LENGTH],
                        # FAQ 접수 안내는 떼고 넘긴다. 저장된 답변에는 남겨 두지만(대화를 다시
                        # 열었을 때 그대로 보여야 한다) 검색어 재작성에 들어가면 안 된다 —
                        # '담당자에게 전달', '알림' 같은 말이 다음 질문과 섞여 엉뚱한 검색어가
                        # 만들어진다(파일 확인 버튼을 대화로 저장하지 않는 것과 같은 이유).
                        "prev_answer": _strip_faq_notice(prev_answer.content)[:MAX_PREV_LENGTH],
                        "prev_topic": prev_answer.topic,
                    }
                break

        # 검색·라우팅은 한국어를 전제로 한다 — 코퍼스도, 토픽 분류 문장도, 검색어 재작성
        # 프롬프트도 전부 한국어다. 비한국어 질문을 그대로 넣으면 재작성이 그 언어로 나와
        # 한국어 문서를 찾지 못한다(실측 기준선: KO 7/7 · EN 3/7 · ZH 4/7).
        # 입구에서 한국어로 옮기면 그 뒤 단계는 한국어 질문과 같은 조건이 된다.
        #
        # 저장·표시에는 쓰지 않는다. chat_message에는 학생이 실제로 친 원문이 남아야 하고,
        # 미답변 수집도 원문으로 한다(관리자가 무엇을 물었는지 그대로 봐야 한다).
        from app.services.translation_service import translate_question_to_korean
        search_question = await translate_question_to_korean(request.question)

        # 순환 import 방지를 위해 런타임에 가져온다.
        from app.agents.agent_graph import agent_graph

        result = await agent_graph.run(
            question=search_question,
            student_id=student_id,
            db=db,
            pending_file=request.pending_file,
            pending_context=request.pending_context,
            prev_context=prev_context,
            file_confirm=request.file_confirm,
        )

        # RAG 경로에서 질문이 재작성됐으면 원본 질문(user_msg) 행에 기록 (파인튜닝 데이터용)
        if user_msg is not None:
            user_msg.rewritten_query = getattr(result, "rewritten_query", None)

        # 답변에 딸린 카드(지도·학사일정·학과·파일제안) — 있는 것만 저장해 과거 대화 복원 시 되살린다.
        card_meta = {
            k: v for k, v in {
                "map_card": result.map_card,
                "schedule_card": getattr(result, "schedule_card", None),
                "dept_card": result.dept_card,
                "scholarship_card": getattr(result, "scholarship_card", None),
                "weather_card": getattr(result, "weather_card", None),
                "file_offer": result.file_offer,
            }.items() if v
        } or None

        # 답변을 화면에 보일 언어로 번역한 뒤, DB에도 '그 번역본'을 저장한다 — 과거 대화를 다시
        # 열었을 때 채팅했던 언어 그대로 보이게 하기 위함(한국어면 번역 없이 원문 그대로).
        from app.services.translation_service import translate_answer
        localized_answer = await translate_answer(result.answer, request.lang)

        # 답을 못 찾은 경우, 그냥 "찾지 못했어요"로 끝내지 않고 다음에 무슨 일이 생기는지
        # 알려 준다. 안내 없이 끝나면 학생은 그 질문을 포기하거나 같은 것을 계속 다시 친다.
        #
        # 번역이 끝난 문장에 붙이는 이유 — 안내 문구는 화면 언어별로 미리 써 둔 고정 문장이라
        # 번역을 거칠 필요가 없다. 번역 전에 붙이면 LLM이 이 문장까지 다시 번역하면서
        # 표현이 매번 달라진다(약속하는 문장이라 흔들리면 안 된다).
        from app.services import faq_service
        unanswered = faq_service.should_collect(
            result.answer, getattr(result, "source", None),
            getattr(result, "topic", None), request.question,
        )

        # 게스트는 수집하지 않는다. 이 기능의 핵심은 '답변이 등록되면 알려 준다'인데
        # 알림은 학번에 붙어 나가므로 비로그인에게는 도착할 방법이 없다. 수집만 하고
        # 알림을 못 보내면 관리자는 답을 썼는데 물어본 사람은 영영 모르는 상태가 된다.
        # 이미 등록된 FAQ를 answer로 돌려주는 것은 이와 별개로 게스트도 그대로 받는다.
        collecting = unanswered and not is_guest
        if collecting:
            localized_answer += _FAQ_PENDING_NOTICE.get(request.lang or "ko", _FAQ_PENDING_NOTICE["ko"])
        elif unanswered and is_guest:
            # 약속은 하지 않되, 로그인하면 무엇이 달라지는지는 알려 준다.
            localized_answer += _FAQ_GUEST_HINT.get(request.lang or "ko", _FAQ_GUEST_HINT["ko"])

        asst_msg = None
        if not is_guest:
            asst_msg = ChatMessage(
                session_id=session.id,
                student_id=current_user.id,
                role="assistant",
                content=localized_answer,
                intent=getattr(result, "intent", None),
                topic=getattr(result, "topic", None),
                source=getattr(result, "source", None),
                source_file=getattr(result, "source_file", None),
                card_meta=card_meta,
            )
            db.add(asst_msg)

            session.last_message_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(asst_msg)

        # 답하지 못한 질문은 관리자 검토 목록으로 넘긴다(FAQ 후보).
        # 커밋 뒤에 기록하는 이유는 asst_msg.id를 함께 남기기 위해서다 — 관리자가 목록에서
        # 원래 대화를 열어 맥락을 볼 수 있어야 답변을 제대로 쓸 수 있다.
        #
        # 판정은 반드시 '번역 전 원문'(result.answer)으로 한다. chat_message에 저장되는 것은
        # 화면 언어로 번역된 문장이라, 영어·중국어로 물으면 한국어 '못 찾음' 표현이 하나도
        # 걸리지 않아 수집이 통째로 새어 나간다.
        #
        # 기록은 INSERT 한 번뿐이라 여기 두어도 되지만, LLM 선별은 수백 ms가 걸리므로
        # 응답을 보낸 뒤 백그라운드에서 돌린다(schedule_classify).
        #
        # 조건은 위에서 이미 판정한 collecting을 그대로 쓴다. 여기서 다시 검사하면
        # 안내는 나갔는데 수집은 안 되는 어긋남이 생길 수 있다 — 지키지 못할 약속이 된다.
        #
        # 커밋은 record()가 스스로 한다(faq_service의 트랜잭션 규칙). 여기서 또 부르면
        # 아무 일도 하지 않는 빈 커밋이 되고, '누가 트랜잭션 주인인가'가 흐려진다.
        #
        # collecting에는 이미 'not is_guest'가 들어 있다(위 판정 참고) — 게스트 질문은
        # 수집하지 않으므로 여기서 student_id가 None인 경우는 생기지 않는다.
        if collecting:
            _uid = await faq_service.record(
                db, request.question,
                rewritten=getattr(result, "rewritten_query", None),
                topic=getattr(result, "topic", None),
                student_id=student_id,
                message_id=asst_msg.id if asst_msg else None,
            )
            faq_service.schedule_classify(_uid)

        return ChatResponse(
            answer=localized_answer,   # 저장한 번역본과 동일 (번역 1회)
            session_id=session.id if session else None,
            message_id=asst_msg.id if asst_msg else None,
            file_offer=result.file_offer,
            file_download=result.file_download,
            map_card=result.map_card,
            schedule_card=getattr(result, "schedule_card", None),
            dept_card=result.dept_card,
            scholarship_card=getattr(result, "scholarship_card", None),
            weather_card=getattr(result, "weather_card", None),
            pending_context=result.pending_context,
            rewritten_query=getattr(result, "rewritten_query", None),
            login_required=bool(getattr(result, "login_required", False)),
            topic=getattr(result, "topic", None),
        )

    async def get_my_sessions(self, db: AsyncSession, current_user: Student) -> list[dict]:
        """로그인 학생 본인의 최근 대화 목록 (사이드바용). topic은 필터용."""
        sessions = (await db.execute(
            select(ChatSession)
            .where(ChatSession.student_id == current_user.id, ChatSession.is_deleted == False)
            .order_by(ChatSession.last_message_at.desc())
            .limit(50)
        )).scalars().all()
        if not sessions:
            return []

        session_ids = [s.id for s in sessions]
        # 각 세션의 첫 assistant 메시지 topic (필터 기준)
        min_id_sub = (
            select(ChatMessage.session_id, func.min(ChatMessage.id).label("min_id"))
            .where(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "assistant")
            .group_by(ChatMessage.session_id)
            .subquery()
        )
        topic_rows = (await db.execute(
            select(ChatMessage.session_id, ChatMessage.topic)
            .join(min_id_sub, ChatMessage.id == min_id_sub.c.min_id)
        )).all()
        topic_map = {sid: topic for sid, topic in topic_rows}

        return [
            {
                "id": s.id,
                "title": s.title or "새 대화",
                "topic": topic_map.get(s.id),
                "last_message_at": s.last_message_at,
            }
            for s in sessions
        ]

    async def get_my_session_messages(self, db: AsyncSession, session_id: int, current_user: Student) -> dict:
        """과거 세션 다시 열기 — 본인 세션만 조회 가능."""
        session = await db.get(ChatSession, session_id)
        if not session or session.student_id != current_user.id or session.is_deleted:
            raise LookupError("세션을 찾을 수 없습니다.")
        msgs = (await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )).scalars().all()
        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,        # user / assistant
                    "content": m.content,
                    "topic": m.topic,
                    "source": m.source,
                    "message_id": m.id,
                    # 답변에 딸렸던 카드(지도·학사일정·학과·파일제안)를 그대로 실어 보내 복원한다.
                    "card_meta": m.card_meta or None,
                }
                for m in msgs
            ],
        }

    async def delete_my_session(self, db: AsyncSession, session_id: int, current_user: Student) -> dict:
        """대화 삭제 (soft delete) — 본인 세션만. is_deleted=True로 목록/조회에서 제외."""
        session = await db.get(ChatSession, session_id)
        if not session or session.student_id != current_user.id or session.is_deleted:
            raise LookupError("세션을 찾을 수 없습니다.")
        session.is_deleted = True
        await db.commit()
        return {"ok": True}

    async def save_feedback(
        self,
        request: FeedbackRequest,
        db: AsyncSession,
        current_user: Student,
    ) -> dict:
        message = await db.get(ChatMessage, request.message_id)
        if not message:
            raise LookupError("메시지를 찾을 수 없습니다.")
        if message.student_id != current_user.id:
            raise PermissionError("해당 메시지에 접근할 수 없습니다.")

        existing = await db.scalar(
            select(ChatFeedback).where(ChatFeedback.message_id == request.message_id)
        )
        if existing:
            existing.is_helpful = request.is_helpful
            existing.rating = request.rating
            existing.comment = request.comment
        else:
            db.add(ChatFeedback(
                message_id=request.message_id,
                is_helpful=request.is_helpful,
                rating=request.rating,
                comment=request.comment,
            ))

        await db.commit()
        return {"ok": True}

    async def save_rewrite_feedback(
        self,
        request: RewriteFeedbackRequest,
        db: AsyncSession,
        current_user: Student,
    ) -> dict:
        """개발용 rewrite 피드백 → rewrite_label 저장(파인튜닝 라벨).
        정답 라벨 = 좋으면 모델 rewrite 그대로, 나쁘면 교정값."""
        label = request.model_rewrite if request.is_good else (request.corrected or None)
        reviewer = getattr(current_user, "student_no", None) or str(current_user.id)

        existing = None
        if request.message_id is not None:
            existing = await db.scalar(
                select(RewriteLabel).where(RewriteLabel.message_id == request.message_id)
            )
        if existing:
            existing.question = request.question
            existing.prev_question = request.prev_question
            existing.model_rewrite = request.model_rewrite
            existing.label_rewrite = label
            existing.is_good = request.is_good
            existing.reviewer = reviewer
        else:
            db.add(RewriteLabel(
                message_id=request.message_id,
                question=request.question,
                prev_question=request.prev_question,
                model_rewrite=request.model_rewrite,
                label_rewrite=label,
                is_good=request.is_good,
                source="dev",
                reviewer=reviewer,
            ))
        await db.commit()
        return {"ok": True}

# 싱글톤 인스턴스
chat_service = ChatService()
