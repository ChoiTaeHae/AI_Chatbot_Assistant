"""학사일정 서비스 — graduation처럼 별도 핸들러로 분기되는 전용 서비스.

핵심 설계: 날짜 선별(오늘 기준 진행 중/다가오는/특정 이벤트)은 코드가 DB에서 정확히 수행하고,
LLM은 이미 뽑힌 정확한 날짜를 자연스러운 문장으로 정리만 한다. (RAG+8B는 날짜 비교에 취약)

데이터: academic_schedule 테이블 (haksa_list.jsp 크롤 → schedule_loader 파싱 → 적재).
"""
import asyncio
import re
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import select, or_, and_, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.DB_Table import AcademicSchedule
from app.services.llm_service import llm_service
from app.prompts import SCHEDULE_PROMPT

# 한국 표준시(고정 +9, DST 없음) — 시스템 tzdata 의존 없이 '오늘' 계산
_KST = timezone(timedelta(hours=9))


def _today() -> date:
    return datetime.now(_KST).date()


def _fmt_range(s: date | None, e: date | None) -> str:
    """(start, end) → '7월 27일 ~ 7월 31일' / 하루면 '2월 27일' / 연도 다르면 연도 표기."""
    if not s:
        return "(날짜 미정)"
    if not e or e == s:
        return f"{s.month}월 {s.day}일"
    if s.year == e.year:
        return f"{s.month}월 {s.day}일 ~ {e.month}월 {e.day}일"
    return f"{s.year}년 {s.month}월 {s.day}일 ~ {e.year}년 {e.month}월 {e.day}일"


def _fmt_range_full(s: date, e: date | None) -> str:
    """연도를 항상 붙이는 범위 문자열 — LLM 컨텍스트 전용.

    _fmt_range는 같은 해면 연도를 생략한다(사용자에게 보여줄 땐 그게 자연스럽다).
    그러나 컨텍스트에서는 치명적이다: 같은 이름의 일정이 학년도별로 여러 건 들어오는데
    ('1학기 일반휴학 신청 기간'이 2026·2027 두 건) 연도가 없으면 서로 구분되지 않고,
    프롬프트가 요구하는 '오늘 기준 진행 중/다가오는 판단'에 필요한 정보 자체가 사라진다.
    코드가 DB에서 정확히 뽑아 둔 날짜를 문자열로 만들면서 도로 버리는 셈이라 반드시 붙인다.
    """
    e = e or s
    if e == s:
        return f"{s.year}년 {s.month}월 {s.day}일"
    if e.year == s.year:
        return f"{s.year}년 {s.month}월 {s.day}일 ~ {e.month}월 {e.day}일"
    return f"{s.year}년 {s.month}월 {s.day}일 ~ {e.year}년 {e.month}월 {e.day}일"


def _dedup(rows: list) -> list:
    """같은 (이름, 시작일, 종료일) 행을 접는다. 순서 유지, 먼저 온 것을 남긴다.

    적재 가드(ingest_from_url)가 생겼어도 읽는 쪽에도 둔다:
      - 가드 이전에 쌓인 과거 데이터가 그대로 남아 있다
      - 학년도 라벨만 다른 중복(같은 행사가 AY2025·AY2026 두 벌)은 적재 키로는
        서로 다른 행이라 가드를 통과한다
    학년도를 키에서 빼는 이유가 이것이다 — 사용자에게는 날짜가 같으면 같은 일정이다.
    컨텍스트에 같은 줄이 두 번 들어가면 모델이 데이터 오류로 받아들인다.
    """
    seen, out = set(), []
    for r in rows:
        key = (r.event, r.start_date, r.end_date)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# 컨텍스트 말머리가 답변에 그대로 새어 나온 것을 떼어내는 패턴.
# 프롬프트로 "말머리는 쓰지 말라"고 해도 8B는 불안정하게 흘린다 — 실측에서 '성적' 질문은
# 문장화했지만 '휴학' 질문은 '다음 일정:'째로 복사했다. rag_general의 _STOP_MARKERS와 같은
# 성격의 안전망이다(그쪽엔 있는데 schedule 핸들러엔 없었다).
# 강조 기호는 콜론 앞뒤 어디에도 올 수 있다(**다음 일정**: / **다음 일정:**) — 양쪽 다 흡수한다.
_LABEL_LEAK_RE = re.compile(
    r"^[ \t]*[*_]{0,2}\s*(?:다음 일정|진행 중|전체 목록)\s*[*_]{0,2}\s*:\s*[*_]{0,2}[ \t]*", re.M
)


def _strip_context_labels(answer: str) -> str:
    """답변에 남은 '다음 일정:' 류 말머리 제거. 내용은 보존한다."""
    cleaned = _LABEL_LEAK_RE.sub("", answer)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


# 파생 일정을 가리키는 수식어 — 본 일정과 이름이 겹쳐 헤드라인이 뒤바뀌는 원인이 된다.
_DERIVED_QUALIFIERS = ("변경", "정정")


def _drop_derived(hit: list, kw_text: str) -> list:
    """질문이 '변경·정정'을 직접 묻지 않았으면 파생 일정을 후보에서 뺀다. 빼서 비면 원래대로."""
    if not any(q in kw_text for q in _DERIVED_QUALIFIERS):
        base = [r for r in hit if not any(q in (r.event or "") for q in _DERIVED_QUALIFIERS)]
        if base:
            return base
    return hit


def _narrow_by_specific_keyword(rows: list, keywords: list[str]) -> list:
    """가장 구체적인(긴) 키워드에 맞는 행만 남긴다 — 헤드라인 선정 전용.

    조회는 키워드 OR 매칭이라 '성적 이의신청'을 물으면 '성적입력 및 성적공고'까지 딸려 온다.
    전체 목록에 남는 건 유용하지만(관련 일정 안내), 헤드라인까지 그중 가장 가까운 것으로
    잡으면 질문과 다른 일정을 답으로 내놓는다.
    실측: '성적 이의신청 언제야' → 헤드라인이 '성적입력 및 성적공고 기간'이 됐다.

    파생 수식어('변경'·'정정')는 한 겹 더 걸러야 한다. 위 매칭은 부분 포함이라 '수강신청'이
    '수강신청 변경 기간'에도 걸리는데, 이건 이름이 비슷할 뿐 다른 기간이다.
    실측: '수강신청 언제야' → 헤드라인이 '2학기 수강신청 변경 기간'이 되고, 모델이 옮겨
    적으며 '변경'을 흘려 "2학기 수강신청은 8월 12일부터"라고 단정했다(실제 수강신청은
    7/27~31로 이미 종료). 프롬프트로 "'변경'을 빼지 마라"를 지시해봤더니 8B가 오히려 더
    흘려 멀쩡하던 '수강정정 기간' 답변까지 깨졌다(실측) → 후보 단계에서 코드로 정리한다.
    질문이 '변경·정정'을 직접 물었으면 그대로 두고, 걸러낸 결과가 비면 원래 후보를 쓴다.
    (전체 목록에는 어느 경우든 그대로 남으므로 정보가 사라지지 않는다)

    키워드가 여럿이면 '가장 긴 것 하나'로는 부족하다 — 나머지 키워드가 통째로 버려진다.
    실측: '겨울학기 언제 개강해' → 긴 쪽('겨울학기')만 써서 겨울학기 수강신청·개강·종강·
    성적입력이 전부 후보로 남았고, 그중 가장 가까운 '겨울학기 수강신청 기간(11/25)'이
    헤드라인이 됐다(정답은 '겨울학기 개강 12/21'). 그래서 키워드를 모두 품은 행을 먼저
    본다. 교집합이 비면(예: '계절학기 수강신청' — DB 이름은 '겨울학기 수강신청 기간'이라
    '계절학기'가 안 들어감) 기존대로 긴 키워드 순으로 내려간다.
    """
    if len(keywords) > 1:
        kws = [k.replace(" ", "") for k in keywords]
        both = [r for r in rows
                if all(k in (r.event or "").replace(" ", "") for k in kws)]
        if both:
            return _drop_derived(both, "".join(kws))
    for kw in sorted(keywords, key=len, reverse=True):
        hit = [r for r in rows if kw in (r.event or "").replace(" ", "")]
        if hit:
            return _drop_derived(hit, kw)
    return rows


def _headline(rows: list, today: date, keywords: list[str] | None = None) -> str:
    """컨텍스트 맨 위에 놓을 '핵심 한 줄' — 어느 일정을 답으로 삼을지 코드가 정한다.

    모델에 '종료된 것 말고 다가오는 것을 골라라'까지 맡기면 규칙 하나를 흘린다.
    실측: 종료된 일정이 섞이자 "2학기 일반휴학 신청 기간은 종료되었어요."로 끝내고,
    바로 윗줄에 있던 다가오는 일정(2027년 1월)을 빠뜨려 '언제야'라는 질문에 답하지 못했다.
    → 고르는 일 자체를 코드가 끝내고 모델은 옮겨 적게 한다. (이 서비스의 기본 원칙)

    rows는 시작일 오름차순이라 처음 만나는 것이 가장 가까운 일정이다.
    """
    row, state = pick_headline_row(rows, today, keywords)
    if row is None:
        return "다음 일정: 없음 (조회된 일정이 모두 지났습니다)"
    prefix = _HEADLINE_PREFIX[state]
    return f"{prefix}: {row.event} — {_fmt_range_full(row.start_date, row.end_date)}"


# pick_headline_row가 돌려주는 상태별 말머리.
_HEADLINE_PREFIX = {"ongoing": "진행 중", "upcoming": "다음 일정", "past": "가장 최근(종료)"}


def pick_headline_row(rows: list, today: date, keywords: list[str] | None = None):
    """헤드라인으로 삼을 행과 그 상태(ongoing/upcoming/past)를 반환.

    헤드라인은 코드가 골라 주는데 전체 목록은 날짜순이라, 둘의 첫 줄이 어긋나면 모델이
    헤드라인을 버리고 목록 맨 위를 답으로 삼는다. 실측: '수강신청 언제야'에서 헤드라인은
    '겨울학기 수강신청 기간(11/25)'이었는데 답변은 목록 첫 줄인 '2학기 수강신청 변경
    기간(8/12)'을 "2학기 수강신청은 8월 12일부터"라고 옮겨 적었다. 고른 행을 목록에서도
    맨 앞에 두면 어느 쪽을 보든 같은 답이 된다.

    다가오는 일정이 없으면 '가장 최근에 끝난 것'까지 내려간다. 여기서 None을 돌려주면
    호출부의 '첫 줄을 코드가 확정' 장치가 통째로 꺼져 버려서, 정작 물어본 날짜를 모델이
    목록에서 알아서 찾아 쓰는 상태로 되돌아간다. 실측: '여름학기 언제 개강해'(8/3 기준
    여름학기가 전부 과거) → 첫 줄이 "관련 일정이 모두 지났어요."로 끝나고 정답인
    개강일(6/22)은 목록에서 찾아 읽어야 했다. 종료 사실은 말머리와 (종료됨) 표시로 전한다.
    """
    pool = _narrow_by_specific_keyword(rows, keywords) if keywords else rows
    ongoing = next((r for r in pool if r.start_date and r.start_date <= today
                    and (r.end_date or r.start_date) >= today), None)
    if ongoing:
        return ongoing, "ongoing"
    upcoming = next((r for r in pool if r.start_date and r.start_date > today), None)
    if upcoming:
        return upcoming, "upcoming"
    # 전부 과거 — 가장 늦게 끝난 것을 쓴다. rows 순서는 호출부마다 다르므로(다가오는 것
    # 다음에 최근 과거가 붙는 식) 순서에 기대지 않고 날짜로 직접 고른다.
    recent = max((r for r in pool if r.start_date),
                 key=lambda r: (r.end_date or r.start_date), default=None)
    return recent, "past"


def _schedule_lines(rows: list, today: date) -> str:
    """'- 이름: 2026년 7월 13일 ~ 7월 17일 (종료됨)' 목록. 전용 답변/보강 공용.

    종료 표시를 코드가 직접 붙인다 — 8B 모델에 날짜 비교를 맡기지 않는다는 이 서비스의
    설계 원칙과 같은 이유다.
    """
    lines = []
    for r in rows:
        if not r.start_date:
            continue
        end = r.end_date or r.start_date
        mark = " (종료됨)" if end < today else ""
        lines.append(f"- {r.event}: {_fmt_range_full(r.start_date, r.end_date)}{mark}")
    return "\n".join(lines)


# ── 타 토픽 보강용 날짜 의도어 ────────────────────────────────────────
# 절차·서류 설명은 RAG 문서에, 실제 날짜는 이 테이블에만 있다. 토픽 라우팅은 배타적
# 선택이라 어느 쪽으로 가든 반쪽 답이 되므로, schedule을 '가져가는 토픽'이 아니라
# 'RAG 답변에 날짜를 얹어 주는 보강 레이어'로도 쓴다.
#
# agent_graph의 게이트 날짜 의도어보다 넓다. 게이트는 토픽을 통째로 가로채는 판단이라
# 오탐 비용이 크지만, 여기는 문장 몇 줄을 덧붙일 뿐이라 놓치는 쪽이 더 아프다.
_AUG_DATE_INTENT = ("언제", "며칠", "몇월", "몇일", "날짜", "기간", "기한", "마감", "일정", "스케줄")


def has_date_intent(question: str) -> bool:
    """질문에 날짜를 묻는 의도가 있는가 (보강 여부 판단용)."""
    qn = question.replace(" ", "")
    return any(k in qn for k in _AUG_DATE_INTENT)


class ScheduleService:

    # LLM 프롬프트 폭주 방지 — 컨텍스트에 넣을 최대 일정 수.
    # 지난 일정은 "방금 끝났다"를 확인시켜 주는 용도라 소수면 충분하다. 많이 넣을수록
    # 모델이 종료된 날짜를 답으로 고를 위험만 커지고, 답변도 나열 벽이 된다.
    # (예: '성적 이의신청 언제야' → 11건 중 5건이 지난 일정이었다)
    _MAX_ITEMS = 8
    _MAX_PAST_ITEMS = 2

    # 보강으로 덧붙일 때의 상한. RAG 컨텍스트(최대 4000자) 위에 얹히므로
    # 로컬 모델 n_ctx(4096) 여유를 남기려고 답변 전용(_MAX_ITEMS)보다 적게 잡는다.
    _AUG_MAX_ITEMS = 5

    # ── 관리자: URL 크롤 → 적재 ────────────────────────────────────
    async def ingest_from_url(self, url: str, db: AsyncSession, keep_recent_years: int = 2) -> int:
        """학사일정 URL을 크롤·파싱해 academic_schedule에 적재. 같은 URL 데이터는 교체(멱등)."""
        from app.rag.Loader.schedule_loader import fetch_schedule_html, parse_schedule_html

        loop = asyncio.get_event_loop()
        # 껍데기 페이지(index.jsp?code=...)면 내부 call('...jsp') include를 따라가 실제 표를 가져옴
        html, _effective = await loop.run_in_executor(None, fetch_schedule_html, url)
        # source_url은 사용자가 입력한 url 그대로 → 같은 입력 재크롤 시 멱등 삭제
        rows = parse_schedule_html(html, url, keep_recent_years=keep_recent_years)

        # 이 URL의 기존 행을 먼저 지운다 → 아래 '기존 키' 조회에 자기 자신의 옛 행이 안 섞인다.
        await db.execute(delete(AcademicSchedule).where(AcademicSchedule.source_url == url))

        # ── 유니크 가드 ────────────────────────────────────────────
        # source_url 단위 교체(위 delete)는 '같은 URL 재크롤'만 멱등하게 만든다. 서로 다른
        # URL 두 개에 같은 일정이 실려 있으면 그대로 두 벌 쌓인다(실제로 14쌍이 쌓였었다).
        # 중복 원인이 여러 갈래(페이지가 같은 일정을 두 번 실음 / 표 셀 분할로 같은 범위를
        # 두 조각으로 파싱)라 파싱 경로를 각각 고치는 대신 결과 키로 한 번에 막는다.
        # 정책은 '먼저 들어온 것이 이긴다' — 나중 URL의 같은 일정은 건너뛴다.
        existing = set((await db.execute(select(
            AcademicSchedule.track, AcademicSchedule.academic_year, AcademicSchedule.event,
            AcademicSchedule.start_date, AcademicSchedule.end_date,
        ))).all())

        fresh, skipped = [], 0
        for r in rows:
            key = (r.get("track"), r.get("academic_year"), r.get("event"),
                   r.get("start_date"), r.get("end_date"))
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            fresh.append(AcademicSchedule(**r))

        db.add_all(fresh)
        await db.commit()
        dup_note = f" (중복 {skipped}건 건너뜀)" if skipped else ""
        print(f"[Schedule] '{url}' 학사일정 {len(fresh)}건 적재{dup_note}")
        return len(fresh)

    # ── 관리자: CRUD (달력 상세수정) ───────────────────────────────
    async def list_schedules(self, db: AsyncSession, track: str | None = None,
                             academic_year: int | None = None) -> list:
        """학사일정 전체 조회 (달력 렌더용). 트랙/연도 필터 옵션."""
        q = select(AcademicSchedule)
        if track:
            q = q.where(AcademicSchedule.track == track)
        if academic_year:
            q = q.where(AcademicSchedule.academic_year == academic_year)
        q = q.order_by(AcademicSchedule.start_date)
        return list((await db.execute(q)).scalars().all())

    async def create_schedule(self, db: AsyncSession, data: dict) -> AcademicSchedule:
        """일정 1건 수동 추가. end_date 미지정이면 하루짜리(start=end)."""
        if not data.get("end_date"):
            data["end_date"] = data.get("start_date")
        row = AcademicSchedule(**data)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    async def update_schedule(self, db: AsyncSession, schedule_id: int, changes: dict) -> AcademicSchedule:
        """일정 수정. 전달된 필드만 갱신."""
        row = (await db.execute(
            select(AcademicSchedule).where(AcademicSchedule.id == schedule_id)
        )).scalar_one_or_none()
        if not row:
            raise LookupError(f"학사일정 id={schedule_id}를 찾을 수 없습니다.")
        for k, v in changes.items():
            if v is not None:
                setattr(row, k, v)
        await db.commit()
        await db.refresh(row)
        return row

    async def delete_schedule(self, db: AsyncSession, schedule_id: int) -> None:
        row = (await db.execute(
            select(AcademicSchedule).where(AcademicSchedule.id == schedule_id)
        )).scalar_one_or_none()
        if not row:
            raise LookupError(f"학사일정 id={schedule_id}를 찾을 수 없습니다.")
        await db.delete(row)
        await db.commit()

    # ── 관리자: 날짜-게이트 키워드 설정 ────────────────────────────
    async def get_gate_config(self, db: AsyncSession) -> dict:
        from app.models.DB_Table import AppConfig
        from app.agents.agent_graph import DEFAULT_DATE_INTENT, DEFAULT_EVENT_KWS
        row = (await db.execute(select(AppConfig).where(AppConfig.key == "schedule_gate"))).scalar_one_or_none()
        val = (row.value if row else None) or {}
        return {
            "date_intent": val.get("date_intent") or DEFAULT_DATE_INTENT,
            "event_keywords": val.get("event_keywords") or DEFAULT_EVENT_KWS,
        }

    async def update_gate_config(self, db: AsyncSession, date_intent: list[str], event_keywords: list[str]) -> dict:
        """게이트 키워드 저장 + 런타임 즉시 반영(재시작 불필요)."""
        from app.models.DB_Table import AppConfig
        from app.agents.agent_graph import set_schedule_gate
        di = [k.strip() for k in (date_intent or []) if k and k.strip()]
        ek = [k.strip() for k in (event_keywords or []) if k and k.strip()]
        value = {"date_intent": di, "event_keywords": ek}
        row = (await db.execute(select(AppConfig).where(AppConfig.key == "schedule_gate"))).scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(AppConfig(key="schedule_gate", value=value))
        await db.commit()
        set_schedule_gate(di, ek)   # 라이브 프로세스 게이트 즉시 교체
        return value

    # ── 챗봇 진입점 ────────────────────────────────────────────────
    async def answer_schedule_with_metadata(self, question: str, db: AsyncSession) -> tuple[str, dict]:
        track = "대학원" if "대학원" in question else "학부"
        today = _today()
        rows = await self._select_rows(question, track, today, db)

        metadata = {"source": "academic_schedule", "source_file": None, "topic": "schedule", "url": None}
        if not rows:
            # 라우팅이 schedule로 잘못 온 경우(예: '성적' 같은 넓은 이벤트어)도 여기로 떨어진다.
            # 호출부(agent_graph)가 RAG로 폴백할 수 있도록 '매칭 없음'을 표시해 둔다.
            metadata["no_match"] = True
            return ("해당 학사일정을 찾지 못했어요. 관리자에게 학사일정 등록을 요청해 주세요.", metadata)

        # 헤드라인으로 고른 일정을 목록에서도 맨 앞으로 옮긴다 — 어긋나면 모델이 목록 첫 줄을
        # 답으로 삼아 헤드라인이 무력화된다(pick_headline_row 설명 참조).
        kws = self._extract_keywords(question)
        head_row, head_state = pick_headline_row(rows, today, kws)
        if head_row is not None:
            rows = [head_row] + [r for r in rows if r is not head_row]

        # '전체'를 물었으면 텍스트 목록 상한을 올린다(기본 8 → 20).
        wants_all = any(h in question.replace(" ", "") for h in self._ALL_HINTS)
        if wants_all and len(rows) < self._MAX_ITEMS_ALL:
            # generic 경로는 upcoming을 6건으로 끊어 왔으므로, 전체 요청이면 현재 학년도에서 다시 채운다.
            full = await self._current_year_rows(track, today, db)
            if len(full) > len(rows):
                keep_head = rows[0] if rows else None
                rows = ([keep_head] + [r for r in full if r is not keep_head]) if keep_head else list(full)
        text_rows = rows[: (self._MAX_ITEMS_ALL if wants_all else self._MAX_ITEMS)]

        # 프론트 미니 달력 카드.
        # '전체'를 물었을 때만 현재 학년도 전부를 넘긴다. 특정 일정을 물은 질문에까지 전부를
        # 넣으면 카드가 엉뚱한 일정에서 시작한다 — ScheduleCard의 초기 포커스는 '오늘 이후 첫
        # 일정'이라 질문과 무관한 항목이 잡히기 때문이다(실측: '복학 신청 기간 언제야?'인데
        # 카드가 '2학기 수강신청 변경 기간' 1/50로 열렸다).
        card_rows = await self._current_year_rows(track, today, db) if wants_all else rows
        metadata["schedule_card"] = self.build_card(card_rows or text_rows)

        head = _headline(text_rows, today, kws)
        context = f"{head}\n\n전체 목록:\n{_schedule_lines(text_rows, today)}"
        if wants_all and card_rows and len(card_rows) > len(text_rows):
            context += (f"\n\n(현재 학년도 일정은 총 {len(card_rows)}건이며, 위 목록은 그중 "
                        f"가까운 {len(text_rows)}건이다. 나머지는 화면의 달력에서 볼 수 있다.)")
        prompt = SCHEDULE_PROMPT.format(
            today=f"{today.year}년 {today.month}월 {today.day}일",
            context=context,
            question=question,
        )
        # 날짜가 흔들리면 안 되므로 결정론적으로(temp 0.0) 문장화만 시킨다.
        # 전체 요청은 항목이 많아 512로는 중간에 잘린다.
        answer = await llm_service.answer(
            prompt, max_tokens=1536 if wants_all else 512, temperature=0.0)
        answer = _strip_context_labels(answer)

        # 첫 줄(요약)은 코드가 만든 문장으로 덮어쓴다. 모델이 일정 이름을 자기 식으로 바꿔 써서
        # 바로 아래 목록과 모순되는 답이 나왔다 — 실측: 헤드라인이 '겨울학기 수강신청 기간
        # (11/25~27)'인데 첫 줄을 "2학기 수강신청은 11월 25일부터 27일까지예요"로 썼고,
        # 같은 답변의 목록엔 '2학기 수강신청 기간: 7/27~7/31 (종료됨)'이 따로 있었다.
        # 프롬프트로 "이름을 바꾸지 마라"를 지시해봤더니 8B가 오히려 더 흘려 멀쩡하던 답변까지
        # 깨졌다(실측). 고르는 일에 이어 '이름 표기'까지 코드가 확정하고, 모델에게는 목록
        # 문장화만 남긴다(이 서비스의 기본 원칙). 형식은 이미 잘 나오던 답변들과 같다.
        # 이미 끝난 일정을 헤드라인으로 쓸 때는 '(종료됨)'을 코드가 붙인다. 안 붙이면 첫 줄만
        # 읽고 다가올 일정으로 오해한다(목록 쪽엔 _schedule_lines가 이미 같은 표시를 단다).
        if head_row is not None and answer:
            mark = " (종료됨)" if head_state == "past" else ""
            head_line = (f"{head_row.event}: "
                         f"{_fmt_range_full(head_row.start_date, head_row.end_date)}{mark}")
            lines = answer.split("\n")
            i = next((n for n, ln in enumerate(lines) if ln.strip()), None)
            if i is None:
                answer = head_line
            elif lines[i].lstrip().startswith("-"):
                lines.insert(i, head_line + "\n")     # 모델이 요약 없이 목록만 냈으면 앞에 붙인다
                answer = "\n".join(lines)
            elif lines[i].strip() != head_line:
                lines[i] = head_line                  # 모델이 쓴 요약 문장을 교체
                answer = "\n".join(lines)

        # 답변이 비면 목록만이라도 보여준다(헤드라인 줄은 말머리라 제외).
        return (answer or _schedule_lines(rows, today)), metadata

    # ── 날짜/키워드 선별 (정확도 핵심, 코드로 처리) ──────────────────
    async def _select_rows(self, question: str, track: str, today: date, db: AsyncSession) -> list:
        keywords = self._extract_keywords(question)
        base = select(AcademicSchedule).where(AcademicSchedule.track == track)

        # 이벤트 키워드가 있으면 → 그 이벤트들. 단 '이전 학년도'는 제외(현재 학년도는 통째로 유지).
        # → 지난 날짜 질문도 현재 학년도 안에서는 답할 수 있고, 오래된 연도(2025 등) 노이즈는 사라진다.
        # 현재 학년도 데이터에는 다음 해 초 일정까지 포함돼 있어, 하반기에 "1학기 수강신청"을 물어도
        # (다음 해 초 일정) 자연스럽게 나온다. 정렬은 다가오는 것 우선 → 최근 과거 순.
        if keywords:
            return (await self._query_by_keywords(keywords, track, today, db))[: self._MAX_ITEMS]

        # 키워드 없음 — '일정 자체'를 묻는 generic 질문("이번 학사일정", "지금 무슨 기간이야?")에만
        # 오늘 진행 중 + 다가오는 일정을 보여준다. 그 외(임베딩이 schedule로 잘못 보낸 '과잠 신청 언제'
        # 등)는 빈 결과 → 호출부가 no_match로 RAG/FAQ에 폴백 (수강신청 캘린더 오노출 방지).
        qn = question.replace(" ", "")
        if any(h in qn for h in self._GENERIC_SCHEDULE_HINTS):
            return await self._active_and_upcoming(base, today, db)
        return []

    async def _query_by_keywords(self, keywords: list[str], track: str, today: date, db: AsyncSession) -> list:
        """이벤트 키워드로 조회 → 다가오는 것(가까운 순) + 최근 과거(최근 순, _MAX_PAST_ITEMS까지)."""
        current_ay = today.year if today.month >= 3 else today.year - 1
        # 동의어 확장: '시험'→'정기평가'/'수시(중간)평가' 등 DB 실제 이벤트명으로 치환.
        # 매핑에 없는 키워드는 자기 자신을 검색어로 쓴다.
        search_terms: list[str] = []
        for k in keywords:
            search_terms.extend(self._EVENT_SYNONYMS.get(k, [k]))
        # 공백 무시 매칭: '1학기 수강 신청' 이벤트도 '수강신청' 키워드로 잡히게
        norm_event = func.replace(AcademicSchedule.event, " ", "")
        conds = [norm_event.ilike(f"%{t.replace(' ', '')}%") for t in search_terms]
        matched = (await db.execute(
            select(AcademicSchedule)
                .where(AcademicSchedule.track == track)
                .where(or_(*conds))
                .where(AcademicSchedule.academic_year >= current_ay)   # 이전 학년도 제외
                .order_by(AcademicSchedule.start_date)
        )).scalars().all()
        matched = _dedup(matched)
        upcoming = [r for r in matched if r.end_date and r.end_date >= today]
        past = list(reversed([r for r in matched if not (r.end_date and r.end_date >= today)]))
        # 과거 일정은 _MAX_PAST_ITEMS개만 남는데 '최근 순'으로만 자르면 질문이 콕 집은 일정이
        # 잘려나간다. 실측: '여름학기 언제 개강해'(8/3 기준 여름학기가 전부 과거)에서 개강일
        # (6/22)이 성적입력·성적정정에 밀려 컨텍스트에서 사라졌고, 모델이 그 빈자리를
        # '여름학기 개강: 7월 24일'(DB에 없는 행)로 지어냈다. 자르기 전에 질문 키워드를 모두
        # 품은 행을 앞으로 올려, 물어본 일정이 먼저 살아남게 한다. 키워드가 하나뿐이면 모든
        # 후보가 그 하나를 품고 있어 순서가 안 바뀌므로 둘 이상일 때만 적용한다.
        if len(keywords) > 1:
            kws = [k.replace(" ", "") for k in keywords]
            exact = [r for r in past if all(k in (r.event or "").replace(" ", "") for k in kws)]
            if exact:
                past = exact + [r for r in past if r not in exact]
        return upcoming + past[: self._MAX_PAST_ITEMS]

    # ── 타 토픽 보강 (schedule을 배타적 토픽이 아니라 '레이어'로 쓰는 진입점) ──
    async def collect_related(self, question: str, db: AsyncSession) -> list:
        """다른 토픽 답변에 덧붙일 관련 학사일정. 조건이 안 맞으면 빈 리스트.

        두 조건을 모두 만족할 때만 보강한다:
          1) 날짜 의도가 있을 것       — '휴학 사유가 뭐야'에 날짜가 끼어들면 안 된다
          2) 이벤트 키워드가 잡힐 것    — 없으면 '다가오는 일정' 덤프가 되어 노이즈

        (2) 때문에 answer_schedule_with_metadata와 달리 _active_and_upcoming 폴백을
        쓰지 않는다. 폴백을 두면 날짜를 언급한 무관한 질문마다 이번 주 일정이 따라붙는다.
        """
        if not has_date_intent(question):
            return []
        keywords = self._extract_keywords(question)
        if not keywords:
            return []
        track = "대학원" if "대학원" in question else "학부"
        rows = await self._query_by_keywords(keywords, track, _today(), db)
        return rows[: self._AUG_MAX_ITEMS]

    def build_context_block(self, rows: list, keywords: list[str] | None = None) -> str:
        """RAG 컨텍스트 뒤에 덧붙일 학사일정 블록.

        전용 답변과 달리 이 블록은 RAG_GENERAL_PROMPT에 섞여 들어가고 거기엔 날짜 관련
        지침이 전혀 없다. 그래서 오늘 날짜를 블록 머리에 직접 적어 둔다
        (SCHEDULE_PROMPT는 today를 따로 받지만 여기는 그럴 자리가 없다).
        """
        if not rows:
            return ""
        today = _today()
        body = _schedule_lines(rows, today)
        if not body:
            return ""
        head = f"[관련 학사일정] (오늘: {today.year}년 {today.month}월 {today.day}일)"
        # RAG 경로에도 헤드라인을 넣는다. 여긴 프롬프트에 날짜 지침이 없어서, 안 넣으면
        # 모델이 목록 중 종료된 항목을 답으로 골라도 막을 방법이 없다.
        return f"\n\n{head}\n{_headline(rows, today, keywords)}\n{body}"

    def build_card(self, rows: list) -> dict | None:
        """프론트 미니 달력 카드 — 전용 답변/보강 양쪽에서 같은 포맷을 쓴다."""
        events = [
            {
                "event": r.event,
                "start_date": r.start_date.isoformat(),
                "end_date": (r.end_date or r.start_date).isoformat(),
            }
            for r in rows if r.start_date
        ]
        return {"today": _today().isoformat(), "events": events} if events else None

    async def _current_year_rows(self, track: str, today: date, db: AsyncSession) -> list:
        """현재 학년도의 진행 중 + 이후 일정 전부 — 프론트 달력 카드에 넘길 목록.

        답변 텍스트와 카드를 분리하는 이유: 텍스트는 길어지면 읽기 나쁘지만, 달력은 넘겨보는
        UI라 많을수록 좋다. ScheduleCard는 이벤트 수 제한 없이 월 단위로 렌더하고 이전/다음
        네비게이션이 있어(events.length > 1이면 활성) 전부 넘겨도 그대로 동작한다.
        지난 학년도는 제외한다 — 넘겨볼 일이 없고 응답만 무거워진다.
        """
        current_ay = today.year if today.month >= 3 else today.year - 1
        rows = (await db.execute(
            select(AcademicSchedule)
                .where(AcademicSchedule.track == track)
                .where(AcademicSchedule.academic_year >= current_ay)
                .where(or_(AcademicSchedule.end_date >= today,
                           AcademicSchedule.start_date >= today))
                .order_by(AcademicSchedule.start_date)
        )).scalars().all()
        return _dedup(list(rows))

    async def _active_and_upcoming(self, base, today: date, db: AsyncSession) -> list:
        active = (await db.execute(
            base.where(and_(AcademicSchedule.start_date <= today,
                            AcademicSchedule.end_date >= today))
                .order_by(AcademicSchedule.start_date)
        )).scalars().all()
        upcoming = (await db.execute(
            base.where(AcademicSchedule.start_date > today)
                .order_by(AcademicSchedule.start_date).limit(6)
        )).scalars().all()
        return _dedup(list(active) + list(upcoming))[: self._MAX_ITEMS]

    # 학사일정 대표 키워드 — 질문에 등장하면 이벤트 필터로 사용(공백 제거 비교)
    _EVENT_KEYWORDS = [
        "수강신청", "수강정정", "수강변경", "수강철회", "수강취소",
        "개강", "종강", "개학", "여름방학", "겨울방학", "방학",
        "휴학", "복학", "자퇴", "전과", "재입학",
        "등록금", "등록", "분납", "장학",
        "성적정정", "성적입력", "성적공고", "이의신청", "성적",
        "졸업사정", "학위수여식", "졸업식", "졸업", "학위",
        "입학식", "신입생", "편입", "입학",
        "시험", "중간고사", "기말고사", "중간시험", "기말시험",
        "정기평가", "수시평가", "중간평가",
        "보강", "공휴일", "연휴", "축제",
        "계절학기", "여름학기", "겨울학기",
        "복수전공", "부전공", "트랙", "전공배정", "조기졸업", "취득유예",
        "토익", "학점포기", "논문", "종합시험",
    ]

    # 이벤트 키워드가 하나도 없을 때 '전체 학사일정 덤프'를 허용하는 generic 신호.
    # 이게 없으면 임베딩이 schedule로 잘못 보낸 비(非)일정 질문("과잠 신청 언제")까지
    # 다가오는 학사일정(수강신청 등)을 뿌려버린다(실측). 일정 자체를 가리키는 질문에만 덤프하고,
    # 그 외는 빈 결과 → no_match → 상위에서 RAG/FAQ로 폴백시킨다. (공백 제거 후 비교)
    _GENERIC_SCHEDULE_HINTS = ("학사일정", "학사달력", "무슨기간", "스케줄", "캘린더", "달력",
                              "일정표", "주요일정", "학기일정", "전체일정", "전체학사")

    # '전체를 달라'는 신호 — 텍스트 목록 상한을 _MAX_ITEMS(8)에서 _MAX_ITEMS_ALL로 올린다.
    # 8건 상한은 로컬 모델 n_ctx(4096) 여유 때문이었는데(주석 참조) 지금은 Vertex라 그 제약이
    # 없다. 실측: 학부 트랙에 오늘 이후 일정이 50건인데 6건만 나가 '일부만 나온다'는 지적을 받았다.
    _ALL_HINTS = ("전체", "전부", "모두", "다알려", "다보여", "싹")
    _MAX_ITEMS_ALL = 20

    # 학생어 → DB 실제 이벤트명 매핑. 학부 중간/기말은 DB에 '수시(중간)평가'·'정기평가'로
    # 저장돼 있어 '시험'·'중간고사' 글자로는 안 잡힌다. '평가' 통짜로 매칭하면
    # 수업평가 설문('수강소감설문(수업평가)')·역량평가('전공능력성취도 평가')까지 딸려오므로
    # 진짜 시험 이벤트명 두 개만 콕 집어 치환한다. 매핑에 없는 키워드는 그대로 사용.
    _EVENT_SYNONYMS = {
        # '수강정정'은 달력에 없고 같은 뜻이 '수강신청 변경 기간'으로 저장돼 있다. 매핑 없으면
        # '수강정정 기간'이 0건→no_match→RAG로 새서 엉뚱한 재수강 규칙을 답했다(실측).
        "수강정정": ["수강신청 변경", "수강변경"],
        # 달력에 '방학'이라는 이름의 행이 아예 없다(314행 중 0건). 학교가 방학을 별도 일정으로
        # 적지 않고 '종강일~개강일'로만 표기하기 때문이다. 매핑이 없으면 '방학 언제부터'가
        # 0건→no_match→RAG로 새서 "여름방학은 여름학기 2학점 이상 이수 후 시작"이라는
        # 엉뚱한 답이 나갔다(실측). 계절학기는 방학 '안에' 있는 별개 일정이라 섞으면 안 된다.
        # 없는 '방학' 행을 만들어 넣는 대신, 학교가 실제로 적어 둔 경계 일정을 그대로 보여준다.
        "방학": ["1학기 종강일", "2학기 개강일", "2학기 종강일", "1학기 개강일"],
        # 계절을 밝힌 질문엔 그쪽 경계만 준다. 안 나누면 '겨울방학 언제야'에 여름방학 경계
        # (1학기 종강·2학기 개강)까지 섞여 나와 네 줄이 통째로 같은 답이 된다(실측).
        # '방학'만 물었을 땐 위 매핑이 그대로 걸려 네 경계를 다 보여준다(계절 미상이므로).
        "여름방학": ["1학기 종강일", "2학기 개강일"],
        "겨울방학": ["2학기 종강일", "1학기 개강일"],
        "시험": ["정기평가", "수시(중간)평가"],
        "중간고사": ["수시(중간)평가"],
        "중간시험": ["수시(중간)평가"],
        "기말고사": ["정기평가"],
        "기말시험": ["정기평가"],
    }

    def _extract_keywords(self, q: str) -> list[str]:
        qn = q.replace(" ", "")
        found = [kw for kw in self._EVENT_KEYWORDS if kw in qn]
        # 긴 키워드가 이미 매칭됐으면 그 안에 포함된 짧은 키워드는 제거
        # (예: '수강신청'이 잡혔으면 '신청' 같은 하위 매칭 중복 방지 — 여기선 부분포함 정리)
        result: list[str] = []
        for kw in found:
            if not any(kw != other and kw in other for other in found):
                result.append(kw)
        return list(dict.fromkeys(result))


schedule_service = ScheduleService()
