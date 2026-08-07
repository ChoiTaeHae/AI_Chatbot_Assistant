# -*- coding: utf-8 -*-
"""topic 분류 문장 정리 — 코드로 관리하는 topic.sentences 변경분.

실행 (백엔드 컨테이너 안에서):
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/seed_topic_sentences.py'
되돌리기:
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/seed_topic_sentences.py --rollback'

왜 필요한가
    topic.sentences는 라우터가 '이 질문이 어느 주제인가'를 판단하는 유일한 근거다.
    문장 하나가 옆 주제의 질문까지 끌어오면 그 질문은 엉뚱한 핸들러로 간다.

    실측으로 확인한 성질: 임베딩은 '문장의 모양'을 강하게 보고 '무엇에 대한 얘기인지'는
    약하게 본다. 그래서 "오늘 OO 뭐~" 형태의 문장은 OO 자리에 무엇이 오든 끌어당긴다.
      "오늘 수업 뭐 있어?"  ↔  "오늘 학식 뭐야"     0.795
      "오늘 뭐 해?"        ↔  "오늘 뭐 나와?"      0.832
      "내일 시간표 알려줘"   ↔  "내일 학식 메뉴 알려줘" 0.808
    이 때문에 수업·일정·공지·시험·행사 질문이 전부 학식으로 새고 있었다.

    문장을 지우는 대신 '시간어(오늘/내일)를 걷어낸 형태'로 바꾸면, 진짜 학식 질문은
    그대로 잡으면서(학식·점심 같은 주제어가 남아 있으므로) 끌어오기만 사라진다.

검증 (적용 전 실측, 111건 vs 16건)
    학식이면 안 되는 질문 16건 → 학식으로 가는 것 0건 (9건이 이 정리로 빠져나감)
    학식이어야 하는 질문 111건 → 실제 이탈 2건
        "이번 주 뭐 나와?"  0.710 → general 0.624
        "오늘 뭐 나 와?"    0.765 → general 0.682   (띄어쓰기 변형)
    둘 다 학식을 가리키는 단어가 하나도 없는 형태라 원래 애매한 질문이다.

적용 후에는:
    1) docker compose restart backend   (라우터 벡터는 서버 기동 시 계산됨)
    2) 아래 '확인용 질문'을 실제로 던져 답이 그대로 나오는지 본다
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import Topic

# 순서대로 적용된다. rollback은 역순으로 되돌린다.
#   add     : 없으면 추가
#   replace : (기존 문장, 바꿀 문장) — 자리를 지킨 채 교체
#   remove  : 있으면 삭제
SEED: list[dict] = [
    {
        "topic": "dining",
        "note": "'오늘 뭐 나와?'가 general로 새던 문제 (dining 0.6xx < general 0.676)",
        "add": ["오늘 뭐 나와?"],
    },
    {
        "topic": "dining",
        "note": "시간어가 든 문장이 수업·일정·공지·시험 질문을 끌어오던 문제",
        "replace": [
            # "오늘 수업 뭐 있어?"를 0.795로 끌어왔다. '학식'만 남기면 진짜 학식 질문은
            # 그대로 잡히고(오늘 학식 뭐야 → 0.743) 수업 쪽은 떨어진다.
            ("오늘 학식 뭐야", "학식 뭐야"),
            # '점심'만 남기면 general의 "점심 뭐 먹지?"에 뺏긴다(실측 0.723). '메뉴'를
            # 넣어 학식 쪽에 붙여 둔다 — "오늘 점심 뭐야?"가 dining 0.728로 유지된다.
            ("오늘 점심 뭐 나와", "점심 메뉴 뭐야"),
        ],
        # "내일 시간표 알려줘"를 0.808로 끌어왔다. '학생식당 메뉴 알려줘'·'동캠 학식 메뉴
        # 알려줘'가 같은 역할을 하고 있어 빼도 "내일 학식 메뉴 알려줘"는 0.787로 유지된다.
        "remove": ["내일 학식 메뉴 알려줘"],
    },
    {
        "topic": "general",
        "note": "'오늘 점심 뭐먹지?'가 잡담으로 새던 문제 (위 dining 정리의 부작용)",
        # 학사 챗봇에서 '점심 뭐 먹지?'는 잡담이 아니라 학식 질문이다. dining 문장을 정리하자
        # 이 문장이 이겨서 '오늘 점심 뭐먹지?'가 "답해드리기 어려워요"로 나갔다(실측
        # dining 0.737 → general 0.725로 역전).
        # dining에 '오늘 점심 뭐 먹지?'를 넣는 방법도 재봤지만, '오늘 OO 뭐~' 형태가 되살아나
        # 수업·일정·시험 등 6건이 다시 학식으로 샜다. 이쪽에서 빼는 게 부작용이 없다
        # (측정: 학식 유지 12/12, 샌 것 0/13).
        "remove": ["점심 뭐 먹지?"],
    },
]

# 적용 후 프론트에서 직접 확인할 질문 — 정리로 건드린 문장들이 여전히 답하는지 본다.
CHECK = [
    "오늘 학식 뭐야", "오늘 점심 뭐야?", "오늘 점심 뭐 나와", "내일 학식 메뉴 알려줘",
    "오늘 학식 메뉴 알려줘", "내일 학식 뭐야", "오늘 급식 뭐야", "점심 뭐 나와?",
]


async def _get(db, name: str) -> Topic:
    row = (await db.execute(select(Topic).where(Topic.name == name))).scalar_one_or_none()
    if row is None:
        raise SystemExit(f"[중단] topic을 찾을 수 없습니다: {name!r}")
    return row


def _save(topic: Topic, sentences: list[str]) -> None:
    topic.sentences = sentences
    flag_modified(topic, "sentences")   # JSON 컬럼은 리스트 교체를 감지시켜야 한다


async def apply() -> None:
    async with AsyncSessionLocal() as db:
        for entry in SEED:
            topic = await _get(db, entry["topic"])
            sents = list(topic.sentences or [])
            print(f"\n[{topic.name}] {entry['note']}")
            print(f"  문장 {len(sents)}개")

            for text in entry.get("add", []):
                if text in sents:
                    print(f"    · 이미 있음  {text}")
                else:
                    sents.append(text)
                    print(f"    + 추가       {text}")

            for old, new in entry.get("replace", []):
                if new in sents:
                    print(f"    · 이미 교체됨 {new}")
                elif old in sents:
                    sents[sents.index(old)] = new
                    print(f"    ~ 교체       {old}  →  {new}")
                else:
                    print(f"    ! 원본 없음   {old}  (건너뜀)")

            for text in entry.get("remove", []):
                if text in sents:
                    sents.remove(text)
                    print(f"    - 삭제       {text}")
                else:
                    print(f"    · 이미 없음  {text}")

            _save(topic, sents)
            print(f"  → 총 {len(sents)}개")
        await db.commit()

    print("\n완료. 서버를 재시작해야 반영됩니다 (라우터 벡터는 기동 시 계산).")
    print("\n재시작 후 확인할 질문:")
    for q in CHECK:
        print(f"    {q}")


async def rollback() -> None:
    async with AsyncSessionLocal() as db:
        for entry in reversed(SEED):
            topic = await _get(db, entry["topic"])
            sents = list(topic.sentences or [])
            print(f"\n[{topic.name}] 되돌리기 — {entry['note']}")

            for text in entry.get("remove", []):
                if text not in sents:
                    sents.append(text)
                    print(f"    + 복구       {text}")

            for old, new in entry.get("replace", []):
                if new in sents:
                    sents[sents.index(new)] = old
                    print(f"    ~ 복구       {new}  →  {old}")

            for text in entry.get("add", []):
                if text in sents:
                    sents.remove(text)
                    print(f"    - 제거       {text}")

            _save(topic, sents)
            print(f"  → 총 {len(sents)}개")
        await db.commit()
    print("\n되돌리기 완료. 서버를 재시작하세요.")


if __name__ == "__main__":
    asyncio.run(rollback() if "--rollback" in sys.argv else apply())
