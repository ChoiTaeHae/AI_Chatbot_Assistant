# -*- coding: utf-8 -*-
"""FAQ 질문 변형 시드 — 코드로 관리하는 faq_question 추가분.

실행 (백엔드 컨테이너 안에서):
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/seed_faq.py'
되돌리기:
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/seed_faq.py --rollback'

왜 필요한가
    faq.answer(검수된 답변)는 사람이 DB에서 편집하지만, '어떤 말투로 물어도 그 답변에
    닿는가'는 질문 변형 개수에 달려 있다. 변형이 특정 표기에 쏠려 있으면 같은 뜻인데도
    임계값(0.70)을 못 넘는다.
      실측: FAQ 14(과사 운영시간)의 변형 4개가 전부 '과사'라는 줄임말이어서
            '과사 점심때 사람 있어?'는 0.851로 통과하는데
            '학과사무실 점심에 열어?'는 0.692로 미달했다.
            '학과사무실 몇시까지 해?'(0.670)는 '학과'가 걸려 과잠 FAQ를 물어왔다.

    답변을 새로 쓰는 게 아니라 '가는 길'만 넓히는 작업이라 이 파일에 모아 둔다.
    DB에만 있으면 날아갔을 때 복구할 수 없고, 팀원이 뭐가 들어있는지 볼 수도 없다.

앵커 방식
    faq_id를 숫자로 박지 않고 '이미 등록된 질문 변형'으로 찾는다. id는 환경마다 다를 수
    있지만 검수된 질문 문장은 같기 때문. 앵커를 못 찾으면 아무것도 안 하고 멈춘다.

추가 후에는 반드시:
    1) docker compose restart backend      (인덱스는 서버 기동 시에만 만들어짐)
    2) python3 scripts/faq_health_check.py (변형을 늘리면 다른 FAQ와 경계가 부딪힐 수 있음)
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import delete, select, text

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import Faq, FaqQuestion

# 새로 만드는 FAQ — 답변이 아직 없으니 앵커를 못 쓴다. 대신 'marker'(대표 질문 변형)가
# 이미 등록돼 있으면 만든 것으로 보고 건너뛴다(여러 번 돌려도 안전).
NEW_FAQ: list[dict] = [
    {
        "marker": "계절학기 들어야 해?",
        "category": "학사",
        "note": "계절학기 수강 필수 여부 — 물으면 기숙사 FAQ가 나가던 문제",
        # 왜 필요한가: 계절학기를 묻는 질문이 FAQ 8(기숙사 계절학기 추가 이용)에 0.774~0.812로
        # 걸려 기숙사 답변이 그대로 나갔다. FAQ는 변형들 중 '최댓값'을 쓰므로 FAQ 8에 변형을
        # 더 넣어 점수를 낮출 수는 없고, 더 잘 맞는 FAQ를 새로 만들어 이기는 방법뿐이다.
        # 실측: 새 FAQ 추가 후 수강 질문 6/6이 이쪽으로 오고, 기숙사 질문 3/3은 FAQ 8 유지.
        #
        # 답변 출처: 우송대 공식 블로그 'Q1. 계절학기, 꼭 들어야 하나요?' (표현만 정리, 사실 무변경).
        # 숫자·날짜를 넣지 않은 이유: 이 경로는 LLM을 안 거치고 그대로 나가서 교정이 안 되는데,
        # 학교 문서끼리도 최소 수강학점 조항이 어긋나 있다(수강신청_규정 제15조 ②4호는
        # '1학년 겨울학기 이후'부터 미적용, 수강신청 안내표는 2019년 이후 전부 '해당 없음').
        # 학번·학과별 분기를 챗봇이 떠안지 않고 학과 사무실로 넘긴다.
        # 첫 줄(정의)은 변형에 '계절학기가 뭐야?'가 있는데 답변이 '들어야 하나'만 말하고
        # 정작 계절학기가 뭔지는 안 알려줘서 넣었다. 같은 블로그 글의 도입 문단이 출처다.
        "answer": (
            "계절학기는 정규 학기인 1·2학기 외에, 방학 기간 중 단기간 집중 수업을 통해 "
            "학점을 이수할 수 있는 학기입니다.\n"
            "수강 여부는 학과마다 다릅니다.\n"
            "다만 1학년의 경우 대부분의 학과에서 여름 계절학기 수강이 필수인 경우가 많습니다.\n"
            "정확한 내용은 본인의 소속 학과 사무실에 문의해 주세요."
        ),
        # 변형 선정 근거(실측): 아래 5개면 '계절학기'(0.890) '계절학기가뭐야'(0.981)
        # '계절학기 들어야 됨?'(1.000)까지 잡히고, 기숙사 질문은 FAQ 8이 그대로 이긴다.
        # '계절학기 신청해야 돼?'는 뺐다 — '신청'이 흔해 수강신청(0.698)·휴학(0.678)을
        # 임계값 0.70 코앞까지 끌어왔다. 한 단어 '계절학기'도 변형으로 넣지 않는다 —
        # FAQ 8의 '계절학기 때 기숙사...'와 경계가 무너진다.
        "questions": [
            "계절학기 들어야 해?",
            "계절학기 들어야 됨?",
            "계절학기 꼭 들어야 돼?",
            "계절학기가 뭐야?",
            "계절학기 안 들으면 어떻게 돼?",
        ],
    },
]

# [{"anchor": 이미 등록된 질문 변형, "note": 설명, "add": [추가할 변형들]}]
SEED: list[dict] = [
    {
        "anchor": "과사 운영시간이 어떻게 됨?",
        "note": "FAQ 14 (과사 운영시간) — '학과사무실' 정식 표기가 없어 미달하던 문제",
        "add": [
            "학과사무실 운영시간 알려줘",
            "학과사무실 운영시간이 어떻게 돼요?",
            "학과사무실 점심시간 언제야?",
            "학과사무실 점심에 열어?",
            "학과사무실 몇시까지 해?",
            "학과사무실 공휴일에 열어?",
            "학과사무실 주말에 해?",
        ],
    },
    {
        "anchor": "기숙사 통금 있어?",
        "note": "FAQ 5 (기숙사 통금) — 답변에 있는 기숙사 이름으로 물으면 미달하던 문제",
        # 답변이 '청운숙, 유긱 1차 23:00 / 2차 23:50, 솔지오 1차 23:00 / 2차 없음'인데
        # 등록된 질문은 전부 '기숙사 통금~' 형태라 기숙사 이름을 대면 안 걸렸다.
        # 실측: '청운숙 통금 몇시야' 0.656 → 일반(0.70)·엄격(0.75) 둘 다 미달해
        #       답이 있는데도 "자료를 찾지 못했어요"가 나갔다.
        "add": [
            "청운숙 통금 몇시야",
            "청운숙 통금 언제까지야?",
            "솔지오 통금 몇시야",
            "유학생기숙사 통금 몇시야",
        ],
    },
    {
        "anchor": "과 MT 언제가?",
        "note": "FAQ 2 (MT 일정·회비) — 변형이 3개뿐이라 표기가 조금만 달라도 미달하던 문제",
        # 등록된 변형이 '과 MT 언제가?' / '엠티 회비 얼마야' / '학과 엠티 일정 알려줘' 셋뿐이라
        # '신청'이 들어가거나 '앰티'로 잘못 쓰면 임계값을 못 넘었다.
        # 실측: '앰티 신청 언제야?' 0.690 → 검색 0건 임계값(0.70)에도 미달해 학군단 모집
        #       일정(인터넷 접수 3.3~6.12, 신원조사, 면접, 체력 인증서)이 답으로 나갔다.
        #       '엠티 언제 가?' 0.733은 0.70은 넘어 통과하지만 0.75(근거약함 경로)엔 미달이라,
        #       라우팅이 조금만 달라져도 답이 바뀌는 위태로운 상태였다.
        "add": [
            "엠티 언제 가?",
            "엠티 신청 언제야?",
            "앰티 신청 언제야?",
            "앰티 언제 가?",
            "MT 신청 언제야?",
            "학과 MT 회비 얼마야?",
        ],
    },
]


async def _resolve(db, anchor: str) -> int:
    """앵커 질문이 속한 faq_id를 찾는다. 없거나 여러 개면 예외."""
    rows = (await db.execute(
        select(FaqQuestion.faq_id).where(FaqQuestion.text == anchor)
    )).scalars().all()
    if not rows:
        raise SystemExit(f"[중단] 앵커 질문을 찾을 수 없습니다: {anchor!r}\n"
                         f"        DB가 다르거나 원본 변형이 삭제된 상태입니다.")
    if len(set(rows)) > 1:
        raise SystemExit(f"[중단] 앵커가 여러 FAQ에 걸쳐 있습니다: {anchor!r} → {set(rows)}")
    return rows[0]


async def _fix_sequences(db) -> None:
    """id 시퀀스가 max(id)보다 뒤처져 있으면 맞춘다.

    팀원이 관리자 화면·SQL로 id를 명시해 넣으면 시퀀스가 안 따라가고, 그 뒤로는 누가
    INSERT를 해도 'id 키가 이미 있습니다'로 실패한다(실측: faq_question 시퀀스 65 / max 66).
    다음에 발급할 번호만 바꾸는 작업이라 기존 행은 건드리지 않는다.
    """
    for table in ("faq", "faq_question"):
        cur, mx = (await db.execute(text(
            f"SELECT last_value, COALESCE((SELECT max(id) FROM {table}), 0) "
            f"FROM {table}_id_seq"))).first()
        if cur < mx:
            await db.execute(text(f"SELECT setval('{table}_id_seq', {mx})"))
            print(f"  [시퀀스] {table}: {cur} → {mx} (다음 발급 번호만 조정)")


async def _create_new(db) -> None:
    for entry in NEW_FAQ:
        exists = (await db.execute(
            select(FaqQuestion.faq_id).where(FaqQuestion.text == entry["marker"])
        )).scalars().first()
        print(f"\n[새 FAQ] {entry['note']}")
        if exists:
            # 만든 뒤에 답변·변형을 고칠 수 있다. 스크립트가 원본이므로 DB를 여기에 맞춘다
            # (지우고 다시 만들면 faq_id가 바뀌어 운영 중 참조가 끊긴다).
            faq = await db.get(Faq, exists)
            if faq is not None and faq.answer != entry["answer"]:
                faq.answer = entry["answer"]
                print(f"  ~ 답변 갱신 (faq_id={exists})")
                print(f"    answer: {' / '.join(entry['answer'].splitlines())[:70]}")
            else:
                print(f"  · 답변 동일 (faq_id={exists})")
            have = set((await db.execute(
                select(FaqQuestion.text).where(FaqQuestion.faq_id == exists)
            )).scalars().all())
            for q in entry["questions"]:
                if q not in have:
                    db.add(FaqQuestion(faq_id=exists, text=q, enabled=True))
                    print(f"    + 변형 추가: {q}")
            continue
        await _fix_sequences(db)
        faq = Faq(answer=entry["answer"], category=entry.get("category"), enabled=True)
        db.add(faq)
        await db.flush()                      # id 확보
        for q in entry["questions"]:
            db.add(FaqQuestion(faq_id=faq.id, text=q, enabled=True))
        print(f"  + 생성 faq_id={faq.id}, 변형 {len(entry['questions'])}개")
        print(f"    answer: {' / '.join(entry['answer'].splitlines())[:70]}")


async def apply() -> None:
    async with AsyncSessionLocal() as db:
        await _create_new(db)
        for entry in SEED:
            faq_id = await _resolve(db, entry["anchor"])
            answer = (await db.execute(
                select(Faq.answer).where(Faq.id == faq_id))).scalar_one()
            print(f"\n[FAQ {faq_id}] {entry['note']}")
            print(f"  answer: {answer[:60]}...")

            existing = set((await db.execute(
                select(FaqQuestion.text).where(FaqQuestion.faq_id == faq_id)
            )).scalars().all())

            added = 0
            for text in entry["add"]:
                if text in existing:
                    print(f"    · 이미 있음  {text}")
                    continue
                db.add(FaqQuestion(faq_id=faq_id, text=text, enabled=True))
                print(f"    + 추가       {text}")
                added += 1
            print(f"  → {added}개 추가")
        await db.commit()
    print("\n완료. 반영하려면 서버를 재시작하세요 (인덱스는 기동 시 생성).")


async def rollback() -> None:
    async with AsyncSessionLocal() as db:
        for entry in SEED:
            faq_id = await _resolve(db, entry["anchor"])
            res = await db.execute(
                delete(FaqQuestion).where(
                    FaqQuestion.faq_id == faq_id,
                    FaqQuestion.text.in_(entry["add"]),
                )
            )
            print(f"[FAQ {faq_id}] {res.rowcount}개 삭제")
        # 새로 만든 FAQ는 통째로 지운다 (faq_question은 ondelete=CASCADE로 함께 삭제)
        for entry in NEW_FAQ:
            fid = (await db.execute(
                select(FaqQuestion.faq_id).where(FaqQuestion.text == entry["marker"])
            )).scalars().first()
            if fid is None:
                print(f"[새 FAQ] 이미 없음 — {entry['marker']}")
                continue
            await db.execute(delete(Faq).where(Faq.id == fid))
            print(f"[새 FAQ {fid}] 답변·변형 통째로 삭제 — {entry['note']}")
        await db.commit()
    print("\n되돌리기 완료. 서버를 재시작하세요.")


if __name__ == "__main__":
    asyncio.run(rollback() if "--rollback" in sys.argv else apply())
