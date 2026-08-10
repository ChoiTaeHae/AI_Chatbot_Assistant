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
    {
        "topic": "course_registration",
        "note": "'계절학기 수강 필수야?'가 졸업요건 표를 답하던 문제",
        # 라우터는 토픽별 '상위 3문장 평균'으로 점수를 낸다. 이 질문은
        #   graduation 0.800 + 0.715 + 0.681 → 0.732   ← 이겼다
        #   schedule   0.827 + 0.672 + 0.670 → 0.723
        # 로 0.009 차이로 갈렸다. 단일 최고점은 오히려 schedule의 '계절학기는 언제
        # 개강하나요?'(0.827)인데, graduation이 계절학기·필수 관련 문장을 여러 개 갖고 있어
        # 평균에서 이겼다. 언제든 뒤집힐 수 있는 불안정한 상태였다.
        #
        # 더 근본적인 문제: '계절학기를 반드시 들어야 하는가'를 가르치는 문장이 어느 토픽에도
        # 없었다(있던 건 '언제 개강'=일정, '졸업학점 포함'=졸업뿐). 라우터는 배울 자료 없이
        # 비슷한 것 중 하나를 고른 셈이다.
        #
        # 이 질문의 주인은 수강 관련인 course_registration(handler=rag)이다. 그쪽으로 가면
        # rag_general 경로를 타고, 거기 이미 있는 FAQ 폴백이 검수 답변(0.963)을 잡는다.
        # FAQ 선행 게이트를 새로 만들 필요가 없다 — FAQ는 지금처럼 최후 보류로 남는다.
        #
        # 적용 전 시뮬레이션(변경 전 → 후):
        #   계절학기 수강 필수야?          graduation 0.732 → course_registration 0.932
        #   계절학기 꼭 들어야 해?          graduation 0.705 → course_registration 0.925
        #   계절학기 안 들어도 돼?          schedule   0.687 → course_registration 0.885
        #   계절학기는 언제 개강하나요?       schedule   0.850 → 그대로
        #   계절학기로 들은 학점도 졸업학점에?  graduation 0.843 → 그대로
        #   졸업 요건 알려줘 / 수강신청 기간   변화 없음
        "add": [
            "계절학기는 반드시 수강해야 하나요?",
            "계절학기 수강이 의무인가요?",
            "계절학기를 듣지 않아도 되나요?",
            "여름학기나 겨울학기를 꼭 들어야 하나요?",
        ],
    },
    {
        "topic": "grades",
        "note": "'몇 번 결석하면 F야?'가 공결 문서를 잡아 '자료 없음'으로 답하던 문제",
        # 정답('총 수업시수의 1/3 이상 결석 시 F')은 grades의 '성적평가' 문서에 있는데,
        # 라우터가 absence(공결)로 보냈다(0.621, 확신 낮음). topic 필터는 Qdrant 하드 필터라
        # grades 문서가 후보에조차 오르지 못했고, LLM은 "출석 인정 기준은 있으나 F 부여
        # 기준은 없다"고 정확히 답했다 — 검색 범위 문제였지 문서가 없어서가 아니었다.
        #
        # 결석·성적 두 주제에 걸친 질문이라 어느 쪽에 두든 반대쪽에서 같은 문제가 난다.
        # 'F 학점'이라는 결과를 묻는 질문은 성적 쪽이 주인이므로 grades에 문장을 세운다.
        #
        # 적용 전 시뮬레이션 (변경 전 → 후):
        #   몇 번 결석하면 F야?          absence 0.621 → grades 0.811
        #   결석 몇 번까지 괜찮아?         absence 0.682 → grades 0.710
        #   출석 미달로 F 받는 기준이 뭐야?  absence 0.698 → grades 0.772
        #   공결 신청 어떻게 해?          absence 0.933 → 변화 없음
        #   공결 인정 서류 뭐 내야 해?      absence 0.798 → 변화 없음
        #   장례로 출석 인정 며칠 돼?       absence 0.797 → 변화 없음
        "add": [
            "몇 번 결석하면 F를 받나요?",
            "결석 때문에 F가 되는 기준이 뭔가요?",
            "수업시수의 얼마를 결석하면 F인가요?",
        ],
    },
    {
        "topic": "course_registration",
        "note": "'재수강 최대 몇 학점까지야?'가 졸업요건 문서를 잡던 문제",
        # 정답('학기당 6학점 이내, 동일 과목 재학 중 2회')은 course_registration의
        # '수강신청_규정' 문서에 그대로 있는데, 라우터가 graduation으로 보냈다.
        # topic은 Qdrant 하드 필터라 정답 문서가 후보에조차 오르지 못했고, 모델은
        # "제공된 자료에서 확인할 수 없습니다"라고 정확히 답했다 — 검색 범위 문제였다.
        #
        # 점수 차가 0.019(graduation 0.776 vs course_registration 0.757)에 불과했다.
        # '재수강'을 학점 한도의 관점에서 가르치는 문장이 어느 토픽에도 없어서,
        # '최대 몇 학점'이라는 표현만 보고 졸업학점 쪽으로 끌려간 것이다.
        #
        # 적용 전 시뮬레이션(변경 전 → 후):
        #   재수강 최대 몇 학점까지야?   graduation  0.776 → course_registration 0.896
        #   재수강 몇 번까지 돼?        readmission 0.748 → course_registration 0.870
        #   재수강 규정 알려줘          readmission 0.696 → course_registration 0.709
        #     ↑ 유일하게 토픽이 바뀐 기존 질문인데, 재입학(readmission)에 있던 것이
        #       오히려 잘못이었다. 답변 내용은 그대로 유지되는 것을 실측으로 확인했다.
        #   수강신청 최대 몇 학점까지 돼? / 계절학기 꼭 들어야 해? / 졸업 관련 6건  변화 없음
        "add": [
            "재수강은 한 학기에 최대 몇 학점까지 들을 수 있나요?",
            "재수강 가능 학점의 한도가 어떻게 되나요?",
            "같은 과목을 몇 번까지 재수강할 수 있나요?",
        ],
    },
    {
        "topic": "grades",
        "note": "'학점포기 몇 학점까지 돼?'·'F 학점포기 돼?'가 졸업요건 문서를 잡던 문제",
        # 위 재수강과 같은 원인이다. 정답('C+~D0 성적으로 최대 9학점, 재학 중 1회')은
        # grades의 성적 규정에 있고, 'F는 포기 불가'는 검수 FAQ에까지 있는데 둘 다
        # graduation으로 라우팅돼 닿지 못했다(0.792 vs grades 0.723 / 0.748 vs 0.700).
        #
        # '포기'라는 낱말이 학점 총량을 연상시켜 졸업요건으로 끌리는 구조라, 학점포기를
        # '성적 처리'의 관점에서 가르치는 문장을 grades에 세운다.
        #
        # 적용 전 시뮬레이션(변경 전 → 후):
        #   학점포기 몇 학점까지 돼?   graduation 0.792 → grades 0.849
        #   F 받은 과목 학점포기 돼?    graduation 0.748 → grades 0.787
        #   학점포기 어떻게 신청해?     graduation 0.745 → grades 0.826
        #   학사경고·성적 이의신청·결석 F·졸업 관련 기존 15건  변화 없음
        "add": [
            "학점포기는 최대 몇 학점까지 신청할 수 있나요?",
            "학점포기를 신청할 수 있는 성적 범위가 어떻게 되나요?",
            "F 학점도 학점포기가 가능한가요?",
        ],
    },
]

# 적용 후 프론트에서 직접 확인할 질문 — 정리로 건드린 문장들이 여전히 답하는지 본다.
CHECK = [
    "오늘 학식 뭐야", "오늘 점심 뭐야?", "오늘 점심 뭐 나와", "내일 학식 메뉴 알려줘",
    "오늘 학식 메뉴 알려줘", "내일 학식 뭐야", "오늘 급식 뭐야", "점심 뭐 나와?",
    # 계절학기 — 앞의 둘은 FAQ 검수 답변, 뒤의 둘은 각각 학사일정·졸업요건으로 갈라져야 한다
    "계절학기 수강 필수야?", "계절학기 꼭 들어야 해?",
    "계절학기는 언제 개강하나요?", "계절학기로 들은 학점도 졸업학점에 포함되나요?",
    # 결석-F는 grades, 공결 신청은 absence 로 갈려야 한다
    "몇 번 결석하면 F야?", "공결 신청 어떻게 해?",
    # 재수강·학점포기는 졸업요건이 아니라 각각 수강신청·성적 규정에서 답해야 한다
    "재수강 최대 몇 학점까지야?", "학점포기 몇 학점까지 돼?", "F 받은 과목 학점포기 돼?",
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
