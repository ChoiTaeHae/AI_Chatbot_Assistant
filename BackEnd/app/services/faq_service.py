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

트랜잭션 규칙 — 예외 없음
    이 모듈의 쓰기 함수는 **자기 트랜잭션을 스스로 커밋한다.** 호출부는 커밋하지 않는다.
    읽기 함수(list_*/count_*)는 아무것도 커밋하지 않는다.

    한동안 record()만 커밋을 호출부에 맡겼는데, 그 이유("채팅 트랜잭션 한가운데라서")는
    이미 사라진 상태였다 — chat_service는 assistant 메시지를 커밋한 뒤에 record()를 부르므로
    record()가 여는 것은 새 트랜잭션이다. 규칙에 예외가 하나라도 있으면 다음 사람이
    커밋을 빠뜨리거나 두 번 하게 되므로, 예외를 없애고 규칙을 한 줄로 만들었다.

    부수 효과(FAQ 인덱스 재적재)도 같은 원칙을 따른다 — answer_to_faq()가 커밋 뒤에
    직접 재적재한다. 호출부가 기억해서 해야 하는 일로 두면 언젠가 빠진다.
"""
import asyncio
import re

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import Faq, FaqNotification, FaqQuestion, UnansweredQuestion
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

# 마커를 찾을 범위 — 첫 문단에서 잘라 볼 최대 길이(아주 긴 한 줄 답변 방어).
_HEAD_SCAN_CHARS = 200


def _lead(answer: str) -> str:
    """답변의 '첫 문단' — 못 찾음 판정은 여기서만 한다.

    답변 전체나 앞 N자를 훑으면 멀쩡한 답변이 잡힌다. 답을 다 해 놓고 곁가지 하나가
    빠졌다고 덧붙인 줄에 마커가 들어가기 때문이다(실측: 제증명 발급 답변 782자 —
    "제증명 발급 방법은 다음과 같습니다:"로 시작해 발급 방법 4가지를 다 안내한 뒤,
    네 번째 줄에 "※ 세부 발급절차·소요시간이 명시되어 있지 않음"이 붙어 97자 위치에서
    걸렸다. 학생에게 완전한 답변을 주고서 "담당자에게 전달했어요"가 함께 나갔다).

    반대로 진짜 미답변은 첫 문장에서 못 찾았다고 말한다. 코드가 만드는 안내문도,
    LLM이 쓰는 문장도 그렇다:
      · "죄송해요, 해당 내용에 대한 자료를 찾지 못했어요…"
      · "졸업사정에 대한 질문은 제공된 문서에서 확인되지 않습니다…" (뒤에 다른 정보가
        붙어도 물어본 것에는 답하지 못한 것이므로 수집 대상이 맞다)
    """
    for line in (answer or "").split("\n"):
        if line.strip():
            return line[:_HEAD_SCAN_CHARS]
    return ""

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
    # 판정은 첫 문단에서만 한다(_lead 설명 참고). 답변 전체를 훑으면 답을 다 해 놓고
    # 덧붙인 단서 한 줄에 걸려, 완전한 답변에도 "담당자에게 전달했어요"가 함께 나간다.
    lead = _lead(answer)
    return any(m in lead for m in _NOT_FOUND_MARKERS)


def should_collect(answer: str, source: str | None, topic: str | None, question: str) -> bool:
    """수집 대상인가 — record()가 실제로 행을 남길 조건과 같다.

    record()가 내부에서 같은 검사를 또 하는데도 이 함수를 따로 두는 이유는,
    호출부가 학생에게 "FAQ에 등록했어요"라고 **말하기 전에** 판정해야 하기 때문이다.
    record()는 커밋 뒤(asst_msg.id가 필요해서)에 부르므로 그때는 이미 답변 문장이 확정돼 있다.

    두 곳의 조건이 갈라지면 안내만 나가고 수집은 안 되거나(가장 나쁜 경우 — 지키지 못할
    약속을 한다) 반대가 된다. 그래서 조건은 여기 한 벌만 두고 record()는 이걸 그대로 쓴다.
    """
    if topic in _SKIP_TOPICS:
        return False
    if len(_normalize(question)) < _MIN_LEN:
        return False
    return is_unanswered(answer, source)


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

    커밋은 여기서 한다(모듈 규칙). 호출부는 커밋할 필요도, 해서도 안 된다.
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

        # 답변을 기다리는 학생으로 등록한다. 위 upsert가 같은 질문을 한 행으로 합치기 때문에
        # unanswered_question.student_id에는 '맨 처음 물어본 한 명'만 남는다 —
        # 나중에 같은 것을 물은 학생들은 그 컬럼만으로는 알림을 받을 수 없다.
        # 이 행이 곧 "답변 등록되면 알려드릴게요"의 약속이다.
        if student_id is not None:
            await db.execute(
                pg_insert(FaqNotification)
                .values(unanswered_id=row_id, student_id=student_id)
                # 같은 학생이 같은 질문을 반복해도 알림은 하나. 이미 답변을 받아 읽은 뒤라면
                # DO NOTHING이 그 행을 그대로 두는데, 그래도 맞다 —
                # answered 행은 위 upsert의 충돌 대상이 아니라 새 행이 생기기 때문이다.
                .on_conflict_do_nothing(index_elements=["unanswered_id", "student_id"])
            )

        await db.commit()
        # 새로 만들어진 행일 때만 선별한다. 기존 행이면 이미 분류를 마쳤거나(is_academic 확정)
        # 분류에 실패한 것이라, 같은 질문으로 LLM을 다시 부를 이유가 없다.
        #
        # 커밋을 마친 뒤에 id를 돌려주는 것이 중요하다 — 백그라운드 선별(classify)은 별도
        # 세션을 열어 이 행을 다시 읽는데, 커밋 전이면 그 세션에는 행이 보이지 않는다.
        return row_id if occurrences == 1 else None
    except Exception as e:
        # 반드시 롤백해야 한다. 예외를 삼키기만 하면 세션이 '중단된 트랜잭션' 상태로 남아,
        # 호출부가 바로 뒤에서 부르는 db.commit()이 InFailedSQLTransaction으로 터진다
        # → 답변은 이미 커밋됐는데 학생에게는 500이 나가는, 가장 나쁜 형태의 실패가 된다.
        # 이 시점에는 assistant 메시지가 이미 커밋된 뒤라 되돌릴 것도 없다(수집분만 버린다).
        try:
            await db.rollback()
        except Exception:
            pass
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


async def delete_question(db: AsyncSession, row_id: int) -> bool:
    """미답변 질문을 실제로 지운다. 없는 id면 False.

    '제외(ignored)'와 무엇이 다른가 — 겹쳐 보이지만 반대로 동작한다.
      제외: 행을 남긴다. 부분 유니크 인덱스가 answered가 아닌 행 하나만 허용하므로,
            같은 질문이 또 들어오면 이 행의 occurrences만 오른다. 즉 '다시는 목록에
            올라오지 않는다'는 뜻이고, 무엇을 왜 걸렀는지도 남는다.
      삭제: 행을 없앤다. 같은 질문이 다시 들어오면 새 행으로 처음부터 수집되고
            LLM 선별도 다시 돈다. 반복되는 무의미 입력에 쓰면 오히려 계속 쌓인다.

    그래서 기본 손잡이는 제외이고, 삭제는 '기록에 남기면 곤란한 것'을 위한 것이다
    (학번·연락처가 그대로 적힌 질문, 시험 삼아 넣은 입력 등).

    faq_notification은 FK가 CASCADE라 함께 지워진다 — 답변을 기다리던 학생의 구독도
    사라진다는 뜻이다. 아직 답이 없는 질문이라 학생 화면에서 없어지는 것은 없지만,
    '알려주겠다'던 약속은 조용히 취소된다.
    """
    row = await db.get(UnansweredQuestion, row_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def answer_to_faq(db: AsyncSession, row_id: int, answer: str,
                        extra_questions: list[str] | None = None) -> dict:
    """관리자가 작성한 답변을 FAQ로 만들고 원 질문을 answered로 닫는다.

    질문 변형(extra_questions)을 함께 받는 이유 — 학생은 등록된 문장 그대로 묻지 않는다.
    원 질문 하나만 등록하면 표현이 조금만 달라져도 다시 못 찾는다.

    커밋과 FAQ 인덱스 재적재를 모두 여기서 끝낸다. 재적재를 빠뜨리면 표만 바뀌고 답변은
    그대로여서 '고쳤는데 반영이 안 된다'가 되는데, 그걸 호출부가 기억해서 해야 하는 일로
    두면 호출부가 하나 더 생기는 순간 빠진다. 순서(커밋 → 재적재)도 여기서 지킨다 —
    커밋 전에 재적재하면 인덱스가 방금 만든 FAQ를 못 읽고 지나간다.
    """
    row = await db.get(UnansweredQuestion, row_id)
    if row is None:
        raise LookupError(f"미답변 질문을 찾을 수 없습니다: {row_id}")
    # 이미 답변한 질문은 다시 받지 않는다. 저장 버튼을 두 번 누르거나 두 관리자가 같은 항목을
    # 동시에 처리하면, 막지 않을 경우 같은 질문에 FAQ가 두 개 생긴다. FAQ는 매칭되면 LLM을
    # 건너뛰고 그대로 나가므로 중복 등록은 '교정 여지 없는 확정 오답'을 만든다.
    # 알림 쪽 피해도 있다 — is_read가 다시 false로 돌아가, 답을 이미 읽은 학생에게 빨간 점이
    # 또 뜨고 그 링크는 새로 만들어진 다른 FAQ를 가리킨다.
    if row.status == "answered":
        raise ValueError(f"이미 답변이 등록된 질문입니다(FAQ #{row.faq_id}).")

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

    # 이 질문을 기다리던 학생 전원에게 알림을 켠다. 여기서 켜지 않으면 종에 아무것도 뜨지 않아
    # 학생 입장에서는 답변이 등록됐는지 알 방법이 없다(같은 질문을 다시 쳐 보는 수밖에 없다).
    # notified_at을 찍는 것이 곧 '알림 발생'이고, 그 전까지 구독 행은 화면에 보이지 않는다.
    notified = (await db.execute(
        update(FaqNotification)
        .where(FaqNotification.unanswered_id == row_id)
        .values(faq_id=faq.id, notified_at=func.now(), is_read=False)
    )).rowcount

    await db.commit()

    # 재적재 실패는 저장 실패가 아니다. FAQ는 이미 커밋됐고 다음 기동 때 적재되므로,
    # 여기서 예외를 올려 500을 내면 관리자는 저장이 안 된 줄 알고 다시 눌러 본다
    # (그리고 이제 그건 409로 막힌다). reloaded=0으로 알리고 '수동 재적재'로 유도한다.
    from app.services import faq_index
    try:
        await faq_index.warmup()
        reloaded = len(faq_index._index)
    except Exception as e:
        print(f"[FAQ] 인덱스 재적재 실패: {type(e).__name__}: {e}")
        reloaded = 0

    return {"faq_id": faq.id, "question_count": len(seen),
            "notified": notified, "reloaded": reloaded}


# ── 학생 알림 ──────────────────────────────────────────────────
# 관리자 쪽(list_questions/count_pending)과 대칭이지만 반드시 student_id로 잠근다.
# 알림 id는 순차 정수라 남의 id를 찍어 보는 것이 쉽다 — 모든 질의의 WHERE에 본인 조건을
# 함께 넣어, 남의 알림은 조회도 읽음 처리도 되지 않게 한다(404로 떨어진다).


async def list_notifications(db: AsyncSession, student_id: int, limit: int = 50) -> list[dict]:
    """내 알림 목록 — 답변이 등록된 것만. 최근 것부터.

    답변 본문은 faq를 조인해 읽는다(복사해 두지 않는다). 관리자가 FAQ를 수정하면
    학생이 여는 알림도 같이 최신 문장이 되어야 하기 때문이다.
    """
    rows = (await db.execute(
        select(
            FaqNotification.id, FaqNotification.is_read, FaqNotification.notified_at,
            FaqNotification.faq_id, UnansweredQuestion.question, Faq.answer,
        )
        .join(UnansweredQuestion, UnansweredQuestion.id == FaqNotification.unanswered_id)
        .join(Faq, Faq.id == FaqNotification.faq_id)
        .where(FaqNotification.student_id == student_id,
               FaqNotification.notified_at.isnot(None))
        .order_by(FaqNotification.notified_at.desc())
        .limit(limit)
    )).all()
    return [
        {"id": r.id, "question": r.question, "answer": r.answer, "faq_id": r.faq_id,
         "is_read": r.is_read, "notified_at": r.notified_at}
        for r in rows
    ]


async def count_unread(db: AsyncSession, student_id: int) -> int:
    """종 위 빨간 점의 근거."""
    return (await db.execute(
        select(func.count()).select_from(FaqNotification)
        .where(FaqNotification.student_id == student_id,
               FaqNotification.notified_at.isnot(None),
               FaqNotification.is_read.is_(False))
    )).scalar() or 0


async def mark_read(db: AsyncSession, student_id: int, notif_id: int) -> bool:
    """알림 하나를 읽음 처리. 본인 것이 아니면 아무 행도 바뀌지 않아 False."""
    result = await db.execute(
        update(FaqNotification)
        .where(FaqNotification.id == notif_id,
               FaqNotification.student_id == student_id)
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount > 0
