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


class ScheduleService:

    # LLM 프롬프트 폭주 방지 — 컨텍스트에 넣을 최대 일정 수
    _MAX_ITEMS = 12

    # ── 관리자: URL 크롤 → 적재 ────────────────────────────────────
    async def ingest_from_url(self, url: str, db: AsyncSession, keep_recent_years: int = 2) -> int:
        """학사일정 URL을 크롤·파싱해 academic_schedule에 적재. 같은 URL 데이터는 교체(멱등)."""
        from app.rag.Loader.schedule_loader import fetch_schedule_html, parse_schedule_html

        loop = asyncio.get_event_loop()
        # 껍데기 페이지(index.jsp?code=...)면 내부 call('...jsp') include를 따라가 실제 표를 가져옴
        html, _effective = await loop.run_in_executor(None, fetch_schedule_html, url)
        # source_url은 사용자가 입력한 url 그대로 → 같은 입력 재크롤 시 멱등 삭제
        rows = parse_schedule_html(html, url, keep_recent_years=keep_recent_years)

        await db.execute(delete(AcademicSchedule).where(AcademicSchedule.source_url == url))
        db.add_all([AcademicSchedule(**r) for r in rows])
        await db.commit()
        print(f"[Schedule] '{url}' 학사일정 {len(rows)}건 적재")
        return len(rows)

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
            return ("해당 학사일정을 찾지 못했어요. 관리자에게 학사일정 등록을 요청해 주세요.", metadata)

        # 프론트 미니 달력 카드용 — 선별된 일정을 구조화해서 함께 반환(일정이 걸친 '주'만 렌더)
        metadata["schedule_card"] = {
            "today": today.isoformat(),
            "events": [
                {
                    "event": r.event,
                    "start_date": r.start_date.isoformat() if r.start_date else None,
                    "end_date": (r.end_date or r.start_date).isoformat() if (r.end_date or r.start_date) else None,
                }
                for r in rows if r.start_date
            ],
        }

        context = "\n".join(f"- {r.event}: {_fmt_range(r.start_date, r.end_date)}" for r in rows)
        prompt = SCHEDULE_PROMPT.format(
            today=f"{today.year}년 {today.month}월 {today.day}일",
            context=context,
            question=question,
        )
        # 날짜가 흔들리면 안 되므로 결정론적으로(temp 0.0) 문장화만 시킨다.
        answer = await llm_service.answer(prompt, max_tokens=512, temperature=0.0)
        return (answer.strip() or context), metadata

    # ── 날짜/키워드 선별 (정확도 핵심, 코드로 처리) ──────────────────
    async def _select_rows(self, question: str, track: str, today: date, db: AsyncSession) -> list:
        keywords = self._extract_keywords(question)
        base = select(AcademicSchedule).where(AcademicSchedule.track == track)

        # 이벤트 키워드가 있으면 → 그 이벤트들. 단 '이전 학년도'는 제외(현재 학년도는 통째로 유지).
        # → 지난 날짜 질문도 현재 학년도 안에서는 답할 수 있고, 오래된 연도(2025 등) 노이즈는 사라진다.
        # 현재 학년도 데이터에는 다음 해 초 일정까지 포함돼 있어, 하반기에 "1학기 수강신청"을 물어도
        # (다음 해 초 일정) 자연스럽게 나온다. 정렬은 다가오는 것 우선 → 최근 과거 순.
        if keywords:
            current_ay = today.year if today.month >= 3 else today.year - 1
            # 공백 무시 매칭: '1학기 수강 신청' 이벤트도 '수강신청' 키워드로 잡히게
            norm_event = func.replace(AcademicSchedule.event, " ", "")
            conds = [norm_event.ilike(f"%{k}%") for k in keywords]
            matched = (await db.execute(
                base.where(or_(*conds))
                    .where(AcademicSchedule.academic_year >= current_ay)   # 이전 학년도 제외
                    .order_by(AcademicSchedule.start_date)
            )).scalars().all()
            if not matched:
                return []
            upcoming = [r for r in matched if r.end_date and r.end_date >= today]
            past = [r for r in matched if not (r.end_date and r.end_date >= today)]
            # 다가오는 것(가까운 순) + 최근 과거(최근 순)
            return (upcoming + list(reversed(past)))[: self._MAX_ITEMS]

        # 키워드 없음(예: "지금 무슨 기간이야?", "이번 학사일정") → 오늘 진행 중 + 다가오는
        return await self._active_and_upcoming(base, today, db)

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
        return (list(active) + list(upcoming))[: self._MAX_ITEMS]

    # 학사일정 대표 키워드 — 질문에 등장하면 이벤트 필터로 사용(공백 제거 비교)
    _EVENT_KEYWORDS = [
        "수강신청", "수강정정", "수강변경", "수강철회", "수강취소",
        "개강", "종강", "개학", "방학", "휴학", "복학", "자퇴", "전과", "재입학",
        "등록금", "등록", "분납", "장학",
        "성적정정", "성적입력", "성적공고", "이의신청", "성적",
        "졸업사정", "학위수여식", "졸업식", "졸업", "학위",
        "입학식", "신입생", "편입", "입학",
        "중간고사", "기말고사", "정기평가", "수시평가", "중간평가",
        "보강", "공휴일", "연휴", "축제",
        "계절학기", "여름학기", "겨울학기",
        "복수전공", "부전공", "트랙", "전공배정", "조기졸업", "취득유예",
        "토익", "학점포기", "논문", "종합시험",
    ]

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
