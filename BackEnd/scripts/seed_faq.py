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

from sqlalchemy import delete, select

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import Faq, FaqQuestion

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


async def apply() -> None:
    async with AsyncSessionLocal() as db:
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
        await db.commit()
    print("\n되돌리기 완료. 서버를 재시작하세요.")


if __name__ == "__main__":
    asyncio.run(rollback() if "--rollback" in sys.argv else apply())
