"""FAQ 성장 파이프라인 — 답하지 못한 질문을 모아 FAQ로 키운다.

순환 구조
    학생 질문 → 답변 실패 → 여기서 수집 → 관리자가 답변 작성 → FAQ 생성
    → 인메모리 인덱스 즉시 재적재 → 다음 학생은 바로 답을 받음

FAQ를 관리자가 상상해서 만드는 게 아니라 '실제로 막힌 질문'에서 자라게 하는 것이 목적이다.

이름이 비슷한 모듈이 셋이라 경계를 적어 둔다.
    faq_service.py  (여기)  미답변 수집 → 선별 → FAQ 전환. 이 파이프라인만 담당한다.
    faq_index.py            검수된 FAQ의 인메모리 임베딩 인덱스(조회·재적재).
    admin_service.py        관리자 화면의 FAQ CRUD(list/create/update/delete).
FAQ CRUD를 찾는다면 admin_service 쪽이다.

응답 지연을 만들지 않는 설계
    record()는 정규화 + INSERT/UPDATE 한 번뿐이라 학생 응답 경로에 그대로 두어도 된다.
    LLM 선별(classify)은 수백 ms가 걸리므로 응답을 보낸 뒤 백그라운드에서 돌린다.
    선별이 실패하면 is_academic이 None으로 남고, 그 행은 목록에 그대로 보인다
    — 분류가 안 됐다고 질문이 사라지면 안 된다(놓치는 것보다 잡음이 낫다).
"""
import asyncio
import re

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import Faq, FaqQuestion, UnansweredQuestion
from app.prompts import TRIAGE_PROMPT, TRIAGE_SYSTEM_PROMPT

# '답을 못 찾았다'는 뜻으로 답변에 실제로 쓰이는 표현들.
# rag_general·graduation·agent_graph가 각자 다른 문구를 쓰기 때문에 한곳에 모아 둔다.
# (같은 목록이 rag_general에도 있지만, 그쪽은 FAQ 폴백 트리거용이라 목적이 달라 공유하지 않는다 —
#  한쪽을 넓히면 다른 쪽 동작이 같이 바뀌어 버린다.)
_NOT_FOUND_MARKERS = (
    "찾지 못", "찾을 수 없", "제공된 문서에", "관련 자료가 없", "관련 자료를 찾",
    "명시가 없", "명시되어 있지 않", "확인되지 않", "포함되어 있지 않",
    "정보가 없", "내용이 없", "답해드리기 어려",
)

# 수집하지 않을 topic. general(잡담)은 chitchat_gate가 이미 걸러 낸 것이라
# 여기까지 오면 '학사 질문이 아니다'가 확정이다 — LLM을 부를 필요도 없다.
_SKIP_TOPICS = {"general"}

_MIN_LEN = 3          # 이보다 짧은 질문은 의미를 판정할 수 없다
_MAX_KEEP = 500       # normalized 컬럼 길이 상한


# 로그에 남기기 전에 가릴 패턴. 학생이 친 질문에는 학번·연락처가 섞여 들어온다
# ("20240101인데 졸업 되나요?", "010-1234-5678로 연락 주세요").
# DB에는 원문을 그대로 둔다 — 관리자가 답변을 쓰려면 맥락이 필요하고 그쪽은 인증이 걸려 있다.
# 반면 컨테이너 로그는 `docker logs`로 누구나 읽을 수 있어 여기서만 가린다.
# \b(단어 경계)를 쓰면 안 된다 — 파이썬에서 한글도 단어문자라 '20240101인데'처럼 조사가
# 붙으면 경계가 생기지 않아 매칭에 실패한다(실측). 숫자 기준 전후방탐색으로 판정한다.
_MASK_PATTERNS = (
    (re.compile(r"(?<!\d)\d{2,3}-\d{3,4}-\d{4}(?!\d)"), "[전화]"),   # 010-1234-5678 / 042-630-9887
    (re.compile(r"(?<!\d)01[016-9]\d{7,8}(?!\d)"), "[전화]"),        # 하이픈 없는 휴대폰
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[메일]"),
    (re.compile(r"(?<!\d)\d{8,10}(?!\d)"), "[학번]"),                # 전화를 먼저 지운 뒤 남는 긴 숫자
)


def mask_pii(s: str) -> str:
    """로그 출력용 마스킹. 순서가 중요하다 — 전화번호를 먼저 지워야
    하이픈 없는 번호가 학번으로 잘못 가려지지 않는다."""
    out = s or ""
    for rx, rep in _MASK_PATTERNS:
        out = rx.sub(rep, out)
    return out


def _normalize(question: str) -> str:
    """중복 판정용 정규화 — 공백·문장부호만 걷어낸다.

    의미어는 건드리지 않는다. '휴학 어떻게 해?'와 '휴학 어떻게 해'는 같은 질문으로 묶이지만
    '휴학 신청 방법'은 따로 남는다. 뜻이 같은 다른 표현까지 묶으려면 임베딩이 필요한데,
    그건 응답 경로에 40ms를 더하므로 여기서 하지 않는다(관리자가 목록에서 한 FAQ에
    질문 변형으로 여러 개 등록하면 된다 — faq_question 구조가 원래 그걸 위한 것이다).
    """
    s = re.sub(r"[?!.,~·\s\"'()\[\]]+", "", question or "")
    return s[:_MAX_KEEP]


def is_unanswered(answer: str, source: str | None) -> bool:
    """이 답변이 '못 찾음'인가.

    답변에 못 찾음 표현이 있으면 수집한다. 단 검수 FAQ가 근거일 때는 제외한다 —
    FAQ에도 부정형 답변이 있고 그건 '답을 한 것'이다
    (실측: 'F는 학점포기를 할 수 없어요' — source='faq').

    source가 비었을 때만 수집하면 안 된다. 문서를 찾긴 했는데 그 문서로 답을 만들지 못한
    경우에도 source에는 문서명이 남기 때문이다(실측: '내 시간표 알려줘' →
    source='solar_c_카페' + "자료를 찾지 못했어요"). 오히려 이런 경우가 가장 수집 가치가
    높다 — 코퍼스에 관련 문서는 있는데 학생이 물은 것에는 답하지 못한다는 뜻이라,
    FAQ로 채워야 할 구멍을 정확히 가리킨다.

    answer는 반드시 '번역 전 원문'을 넘겨야 한다. chat_message에 저장되는 것은 화면 언어로
    번역된 답변이라, 영어·중국어로 물으면 한국어 마커가 하나도 걸리지 않는다.
    """
    if source == "faq":
        return False
    return any(m in (answer or "") for m in _NOT_FOUND_MARKERS)


async def record(
    db: AsyncSession,
    question: str,
    *,
    rewritten: str | None = None,
    topic: str | None = None,
    student_id: int | None = None,
    message_id: int | None = None,
) -> int | None:
    """미답변 질문을 기록한다. 같은 질문이 이미 대기 중이면 occurrences만 올린다.

    반환값은 행 id(백그라운드 선별에서 쓴다). 수집 대상이 아니면 None.
    이 함수는 학생 응답 경로에서 호출되므로 예외를 밖으로 내보내지 않는다 —
    수집이 실패해도 학생에게는 답변이 정상적으로 나가야 한다.
    """
    try:
        if topic in _SKIP_TOPICS:
            return None
        norm = _normalize(question)
        if len(norm) < _MIN_LEN:
            return None

        # SELECT 후 INSERT로 나누면 동시 요청에서 집계가 샌다 — 두 요청이 같은 시점에
        # '없음'을 보고 둘 다 INSERT하면 하나는 유니크 위반으로 버려지고 그 횟수는 사라진다
        # (실측: 같은 질문 5회 동시 입력 → 2회만 집계, 3회 유실).
        # occurrences는 관리자가 우선순위를 정하는 유일한 신호라 숫자가 틀리면 안 된다.
        # → INSERT ... ON CONFLICT DO UPDATE 한 문장으로 원자적으로 처리한다.
        #
        # 충돌 대상은 부분 유니크 인덱스(uq_unanswered_open: status <> 'answered')다.
        # 그래서 이미 filtered·ignored로 닫아 둔 질문이 다시 들어와도 그 행의 횟수만 올라간다
        # — 예전에는 pending 행만 찾아서, 걸러 낸 질문이 반복되면 새 행이 계속 생기고
        # LLM 선별도 매번 다시 돌았다.
        stmt = (
            pg_insert(UnansweredQuestion)
            .values(question=question, normalized=norm, rewritten=rewritten,
                    topic=topic, student_id=student_id, message_id=message_id)
            .on_conflict_do_update(
                index_elements=[UnansweredQuestion.normalized],
                index_where=text("status <> 'answered'"),
                set_={"occurrences": UnansweredQuestion.__table__.c.occurrences + 1},
            )
            .returning(UnansweredQuestion.id, UnansweredQuestion.occurrences)
        )
        row_id, occurrences = (await db.execute(stmt)).one()
        await db.flush()
        # 새로 만들어진 행일 때만 선별한다. 기존 행이면 이미 분류를 마쳤거나(is_academic 확정)
        # 분류에 실패한 것이라, 같은 질문으로 LLM을 다시 부를 이유가 없다.
        return row_id if occurrences == 1 else None
    except Exception as e:
        print(f"[FAQ] 미답변 기록 실패(무시): {type(e).__name__}: {e}")
        return None


async def classify(row_id: int) -> None:
    """LLM으로 등록 가치를 판정해 행을 갱신한다. 백그라운드 전용.

    자체 세션을 연다 — 요청 세션은 응답이 나가면 닫히기 때문이다.
    학사 무관·부적절로 판정되면 status를 filtered로 바꿔 기본 목록에서 빼되 지우지는 않는다
    (오판을 나중에 확인할 수 있어야 하고, 어떤 질문이 걸러졌는지 자체가 운영 정보다).
    """
    from app.core.Database import AsyncSessionLocal
    from app.services.llm_service import llm_service

    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(UnansweredQuestion, row_id)
            if row is None or row.status != "pending":
                return

            raw = await llm_service.answer(
                TRIAGE_PROMPT.format(question=row.question),
                max_tokens=48,
                system_prompt=TRIAGE_SYSTEM_PROMPT,
                temperature=0.0,
            )
            verdict, _, reason = (raw or "").strip().partition("|")
            verdict = verdict.strip().upper()
            if verdict not in ("YES", "NO"):
                print(f"[FAQ] 선별 형식 이탈 → 분류 보류: {raw!r}")
                return                      # is_academic=None으로 남아 목록에는 보인다

            row.is_academic = (verdict == "YES")
            row.triage_reason = (reason or "").strip()[:200] or None
            if not row.is_academic:
                row.status = "filtered"
            await db.commit()
            print(f"[FAQ] 선별 {verdict} — {mask_pii(row.question[:40])} ({row.triage_reason})")
    except Exception as e:
        print(f"[FAQ] 선별 실패(무시): {type(e).__name__}: {e}")


def schedule_classify(row_id: int | None) -> None:
    """응답을 막지 않도록 선별을 백그라운드로 띄운다.

    create_task 결과를 잡아 두지 않으면 GC가 실행 도중 태스크를 회수할 수 있어
    참조를 모듈 집합에 보관했다가 끝나면 뺀다(파이썬 공식 문서 권고).
    """
    if row_id is None:
        return
    task = asyncio.create_task(classify(row_id))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


_pending_tasks: set[asyncio.Task] = set()


# ── 관리자 조회·처리 ────────────────────────────────────────────
async def list_questions(db: AsyncSession, status: str = "pending", limit: int = 100) -> list[dict]:
    """검토 목록. 많이 물어본 것부터, 같으면 최근 것부터."""
    rows = (await db.execute(
        select(UnansweredQuestion)
        .where(UnansweredQuestion.status == status)
        .order_by(UnansweredQuestion.occurrences.desc(), UnansweredQuestion.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [
        {
            "id": r.id, "question": r.question, "rewritten": r.rewritten,
            "topic": r.topic, "occurrences": r.occurrences, "status": r.status,
            "is_academic": r.is_academic, "triage_reason": r.triage_reason,
            "student_id": r.student_id, "faq_id": r.faq_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def count_pending(db: AsyncSession) -> int:
    """사이드바 배지용 — 관리자가 봐야 할 건수."""
    return (await db.execute(
        select(func.count()).select_from(UnansweredQuestion)
        .where(UnansweredQuestion.status == "pending")
    )).scalar() or 0


async def set_status(db: AsyncSession, row_id: int, status: str) -> bool:
    """관리자가 목록에서 제외(ignored)하거나 되돌린다(pending)."""
    if status not in ("pending", "ignored", "filtered"):
        raise ValueError(f"허용되지 않는 status: {status}")
    result = await db.execute(
        update(UnansweredQuestion)
        .where(UnansweredQuestion.id == row_id)
        .values(status=status)
    )
    await db.commit()
    return result.rowcount > 0


async def answer_to_faq(db: AsyncSession, row_id: int, answer: str,
                        extra_questions: list[str] | None = None) -> dict:
    """관리자가 작성한 답변을 FAQ로 만들고 원 질문을 answered로 닫는다.

    질문 변형(extra_questions)을 함께 받는 이유 — 학생은 등록된 문장 그대로 묻지 않는다.
    원 질문 하나만 등록하면 표현이 조금만 달라져도 다시 못 찾는다.

    인덱스 재적재는 호출부(API)에서 한다 — 여기서 하면 트랜잭션이 커밋되기 전에
    인덱스가 새 FAQ를 읽으려다 못 읽는 순서 문제가 생긴다.
    """
    row = await db.get(UnansweredQuestion, row_id)
    if row is None:
        raise LookupError(f"미답변 질문을 찾을 수 없습니다: {row_id}")

    faq = Faq(answer=answer, category=row.topic, enabled=True)
    db.add(faq)
    await db.flush()

    texts = [row.question] + [q.strip() for q in (extra_questions or []) if q and q.strip()]
    seen: set[str] = set()
    for t in texts:
        key = _normalize(t)
        if key in seen:
            continue
        seen.add(key)
        db.add(FaqQuestion(faq_id=faq.id, text=t, enabled=True))

    row.status = "answered"
    row.faq_id = faq.id
    await db.commit()
    return {"faq_id": faq.id, "question_count": len(seen)}
