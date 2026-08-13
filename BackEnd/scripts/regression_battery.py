# -*- coding: utf-8 -*-
"""챗봇 회귀 배터리 — 라우팅·검색·답변을 실제 파이프라인으로 한 번에 검증.

실행 (백엔드 컨테이너 안에서):
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/regression_battery.py'

케이스: (질문, 기대토픽|None, 답변에 있어야 할 문자열들, 이전질문|None, student_id)
  - 기대토픽 None = 토픽은 확인하지 않음(졸업처럼 핸들러가 토픽을 다시 정하는 경우)
  - 이전질문을 주면 2턴 대화로 실행된다(맥락 의존 버그가 여기서만 재현되는 경우가 많다)
  - 학점 기대값은 아래 main()에서 DB를 읽어 주입한다(__TOTAL__ 자리표시자)

주의: 실제 LLM(Vertex)을 호출하므로 토큰을 소비한다. 429 대비로 호출 간 간격 + 1회 재시도.
"""
import asyncio, sys, io, contextlib, time
sys.path.insert(0, ".")
from app.core.Database import AsyncSessionLocal
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.agents.topic_router import topic_router
from app.agents.agent_graph import agent_graph
from app.server import _load_topics, _load_search_synonyms

NOT_FOUND = ("찾지 못", "찾을 수 없", "제공된 문서에", "관련 자료가 없")
S = 14   # 박민수(학생, dept 7)
A = 5    # admin(학과 없음)

CASES = [
    # ── 병합 앵커(문서 뒤쪽 정답) ──
    ("학사경고 기준이 뭐야", "grades", ["1.50"], None, S),
    ("학사경고 몇 번 받으면 제적이야", "grades", ["3회"], None, S),
    ("기숙사 입사하려면 성적 얼마나 돼야 해?", "dormitory", ["3.00"], None, S),
    # ── campus 게이트 ──
    ("기숙사 입사 제한 대상은?", "dormitory", ["벌점"], None, S),
    ("기숙사 입사 우선순위 알려줘", "dormitory", ["장애인"], None, S),
    ("학생회관 어디야?", "campus", ["위치"], None, S),
    ("기숙사", "campus", ["위치"], None, S),
    ("도서관 몇시까지 해?", "welfare_facilities", ["07:00"], None, S),
    # ── school_rules ──
    ("동아리실 몇 시까지 쓸 수 있어?", "school_rules", ["08:00", "22:00"], None, S),
    ("교내에 현수막 걸려면 어떻게 해?", "school_rules", ["학생복지처"], None, S),
    # ── 졸업 분류기 ──
    ("다전공 꼭 들어야 해?", None, ["다전공"], None, S),
    ("복수전공 필수야?", None, ["전공"], None, S),
    ("1학년 수료 기준 학점이 뭐야?", None, ["34", "2024"], None, S),
    ("편입생은 몇 학점 들어야 졸업해?", None, ["학점"], None, S),
    ("3학년 편입인데 몇 학점 들어야 해?", None, ["편입"], None, S),
    ("학년별 수료 기준 알려줘", None, ["34", "68"], None, S),
    ("2학년 수료하려면 몇 학점?", None, ["68"], None, S),
    ("재증명이 뭐야?", "rag_general", ["증명"], None, S),
    # ── 연도 탐지·폴백 (과거/미래/실재) ──
    ("1999학번 졸업요건 알려줘", None, ["1999", "2020"], None, S),
    ("99학번 졸업요건 알려줘", None, ["1999"], None, S),
    ("2009년 간호학과 졸업요건", None, ["2009", "2020"], None, S),
    ("2029학년도 간호학과 졸업요건", None, ["2029", "2026"], None, S),
    ("2028학번 간호학과 졸업요건", None, ["2028", "2026"], None, S),
    ("2022년 간호학과 졸업요건", None, ["2022"], None, S),
    # 다른 학과를 연도 없이 물으면 '묻는 학생의 입학연도' 기준으로 답해야 한다.
    # (전에는 그 학과의 최신 연도로 답해서 2024학번에게 2025 요건이 나갔다.)
    ("게임그래픽전공 졸업요건", None, ["__MYYEAR__"], None, S),
    # ── 학과 없는 계정 ──
    ("내년에 졸업하려면 뭐 필요해?", None, ["소속 학과 정보가 없"], None, A),
    ("간호학과 졸업요건", None, ["학점"], None, A),
    ("내년에 졸업하려면 뭐 필요해?", None, ["__TOTAL__"], None, S),
    # ── facility_rental (맥락 포함) ──
    ("운동장 빌릴 때 안 되는 행사는?", "facility_rental", ["포교"], None, S),
    ("운동장 빌릴 때 안 되는 행사는?", "facility_rental", ["포교"], "학군단 하면 돈 얼마나 받아?", S),
    ("체육관 대관 취소되는 경우는?", "facility_rental", ["취소"], None, S),
    ("헬스장 운영시간 알려줘", "welfare_facilities", ["07:00"], None, S),
    # ── 특별시험 학점인정 / 오타 / 창작 방지 ──
    ("재수강도 특별학점 처리 가능한가요?", "rag_general", ["재수강"], None, S),
    ("특별학점이 뭐야?", "rag_general", ["95"], None, S),
    ("특별학점 신청 방법", "rag_general", ["대학정보시스템"], None, S),
    ("재증명 어떻게해?", "rag_general", ["증명"], "재증명이 뭐야?", S),
    ("증명서 발급 어디서 해?", "rag_general", ["증명"], None, S),
    ("자격증으로 학점 인정이 되나요?", "rag_general", ["학점"], None, S),
    # ── 기존 기능 회귀 ──
    ("동아리 뭐 있어?", "student_support", ["동아리"], None, S),
    ("휴학 어떻게 신청해?", "leave", ["휴학"], None, S),
    ("복학 절차 알려줘", "return_to_school", ["복학"], None, S),
    ("수강정정 기간 알려줘", "schedule", ["8월"], None, S),
    ("이번학기 주요 일정", "schedule", ["수강신청"], None, S),
    ("학군단 지원 자격이 뭐야", "rotc", ["자격"], None, S),
    ("성적 이의신청 어떻게 해?", "grades", ["교수"], None, S),
    ("전과 신청 자격 알려줘", "major_change", ["재학"], None, S),
    ("공결 신청 어떻게 해?", "absence", ["증빙"], None, S),
    ("졸업 요건 알려줘", None, ["__TOTAL__"], None, S),
    ("장학금 신청 방법", "scholarship", ["장학"], None, S),
    ("재수강 규정 알려줘", None, ["재수강"], None, S),
]


async def run_one(db, q, prev_q, sid):
    ctx = None
    if prev_q:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r0 = await agent_graph.run(question=prev_q, student_id=sid, db=db)
        d0 = r0 if isinstance(r0, dict) else getattr(r0, "__dict__", {})
        ctx = {"prev_question": prev_q, "prev_answer": (d0.get("answer") or "")[:500],
               "prev_topic": d0.get("topic")}
        await asyncio.sleep(1.2)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = await agent_graph.run(question=q, student_id=sid, db=db, prev_context=ctx)
    return r if isinstance(r, dict) else getattr(r, "__dict__", {})


async def main():
    if llm_service.vertex_client is None:
        llm_service._init_vertex()
    topic_router._embedding = rag_service.embedding
    td = await _load_topics()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, topic_router.warmup, td)
    await _load_search_synonyms()
    try:
        from app.services.faq_index import warmup as fw
        await fw()
    except Exception:
        pass

    # 학점 기대값은 DB에서 읽어 주입한다.
    # 하드코딩하면 테스트 계정의 학과·학번이 바뀔 때마다 멀쩡한 기능이 실패로 찍힌다
    # (실측: student 14가 AI·빅데이터학과 126학점 → 솔브릿지경영학부 120학점으로 교체돼
    #  '졸업 요건 알려줘'가 오탐 실패로 잡혔다).
    from sqlalchemy import text as _sql
    async with AsyncSessionLocal() as _db:
        _row = (await _db.execute(_sql("""
            SELECT d.name, rr.min_credits_major, rr.min_credits_liberal, rr.min_credits_total
            FROM student s
            JOIN department d ON d.id = s.dept_id
            JOIN requirement_set rs ON rs.dept_id = s.dept_id
                 AND rs.admission_year = LEFT(s.student_no, 4)::int
            JOIN requirement_rule rr ON rr.set_id = rs.id
            WHERE s.id = :sid
        """), {"sid": S})).first()
        # 테스트 학생의 입학연도. '다른 학과 졸업요건'은 그 학과의 최신 연도가 아니라
        # 묻는 학생의 입학연도 기준으로 답한다(전과해도 졸업요건은 입학연도를 따라간다).
        _myyear = (await _db.execute(_sql(
            "SELECT LEFT(student_no, 4) FROM student WHERE id = :sid"), {"sid": S})).scalar()

    if _row:
        _dept, _maj, _lib, _tot = _row
        _expect = [str(int(_maj)), str(int(_lib)), str(int(_tot))]
        print(f"[기대값] {_dept} — 전공 {int(_maj)} / 교양 {int(_lib)} / 총 {int(_tot)}")
    else:
        _expect = ["학점"]          # 요건 미등록이면 형식만 확인
        print("[기대값] DB에서 요건을 찾지 못함 → '학점' 포함 여부만 확인")

    for _i, _c in enumerate(CASES):
        if "__MYYEAR__" in _c[2] and _myyear:
            CASES[_i] = (_c[0], _c[1], [str(_myyear)], _c[3], _c[4])
            continue
        if "__TOTAL__" in _c[2]:
            CASES[_i] = (_c[0], _c[1], _expect, _c[3], _c[4])

    print("READY\n")

    ok = bad = 0
    fails = []
    t0 = time.time()
    async with AsyncSessionLocal() as db:
        for i, (q, exp_topic, musts, prev_q, sid) in enumerate(CASES, 1):
            d = None
            for attempt in (1, 2):
                try:
                    d = await run_one(db, q, prev_q, sid)
                    break
                except Exception as e:
                    if "429" in str(e) and attempt == 1:
                        print(f"    (429 → 20초 후 재시도: {q})")
                        await asyncio.sleep(20)
                        continue
                    print(f"[ERR] {q} → {type(e).__name__}: {str(e)[:80]}")
                    bad += 1; fails.append(f"{q} → {type(e).__name__}")
                    break
            if d is None:
                await asyncio.sleep(1.2); continue

            ans, topic = (d.get("answer") or ""), d.get("topic")
            probs = []
            if any(m in ans for m in NOT_FOUND):
                probs.append("못찾음")
            if exp_topic and topic != exp_topic:
                probs.append(f"topic={topic}(기대{exp_topic})")
            miss = [m for m in musts if m not in ans]
            if miss:
                probs.append(f"누락{miss}")
            who = "" if sid == S else " [admin]"
            ctxlab = f" [이전:{prev_q}]" if prev_q else ""
            if probs:
                bad += 1; fails.append(f"{q}{who} → {', '.join(probs)}")
                print(f"[{i:2}] ✗ {q}{who}{ctxlab}\n        ⚠ {', '.join(probs)}\n        → {ans[:150]}")
            else:
                ok += 1
                print(f"[{i:2}] ✓ {q}{who}{ctxlab}")
            await asyncio.sleep(1.2)

    print(f"\n{'='*64}\n통과 {ok} / 실패 {bad}  (총 {ok+bad})  소요 {time.time()-t0:.0f}초")
    if fails:
        print("\n실패 목록:")
        for f in fails:
            print("  -", f)

asyncio.run(main())
