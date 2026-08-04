# -*- coding: utf-8 -*-
"""FAQ 자기검증 — 오분류·경계충돌·고립 항목을 찾아낸다.

실행 (백엔드 컨테이너 안에서):
    docker exec ai_chatbot_assistant-backend-1 sh -c 'cd /app && python3 scripts/faq_health_check.py'

왜 필요한가
    FAQ 게이트는 매칭되면 LLM을 건너뛰고 검수 답변을 그대로 내보낸다. 그래서 질문 변형이
    엉뚱한 FAQ에 붙어 있으면 교정 여지 없는 확정 오답이 된다.
    실측: '학포 몇 학점부터 가능한가요?'가 학사경고 FAQ에 등록돼 있어 "평점평균 1.50 미달"
    이라는 무관한 답이 나갔다(학포=학점포기).

판정 방식 (leave-one-out)
    각 질문 변형에서 '자기 자신'을 뺀 뒤 나머지 인덱스와 비교한다. 자기 자신을 두면 유사도가
    1.0이라 무조건 통과해 아무것도 못 잡는다.
      best_same  : 같은 FAQ의 다른 변형 중 최고 유사도  (이 변형을 받쳐주는 힘)
      best_other : 다른 FAQ 변형 중 최고 유사도          (뺏어가는 힘)

    ✗ 오분류   best_other > best_same     → 다른 FAQ가 더 가깝다. 배치가 잘못됐을 가능성.
    ! 취약     margin < MARGIN_WARN       → 근소한 차이. FAQ가 늘면 뒤집힐 수 있다.
    · 고립     같은 FAQ에 변형이 1개뿐    → 비교 대상이 없어 판정 불가(문제는 아님).

    임계값(FAQ_THRESHOLD) 미달 여부도 함께 표시한다 — 실제 사용자 질문은 변형과 다르게
    들어오므로, 변형끼리도 임계값을 못 넘으면 그 FAQ는 사실상 특정 문장에서만 걸린다.
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from app.core.Database import AsyncSessionLocal
from app.models.DB_Table import Faq, FaqQuestion
from app.services.faq_index import FAQ_THRESHOLD, _normalize
from app.services.rag_service import rag_service

# 같은 FAQ가 다른 FAQ를 이 차이 미만으로 겨우 이기면 '취약'으로 본다.
MARGIN_WARN = 0.05


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(FaqQuestion.id, FaqQuestion.text, FaqQuestion.faq_id, Faq.answer)
            .join(Faq, Faq.id == FaqQuestion.faq_id)
            .where(FaqQuestion.enabled == True, Faq.enabled == True)  # noqa: E712
            .order_by(FaqQuestion.faq_id, FaqQuestion.id)
        )).all()

    if not rows:
        print("등록된 FAQ 질문이 없습니다.")
        return

    texts = [r[1] for r in rows]
    vecs = [_normalize(v) for v in rag_service.embedding.embed_texts(texts)]
    n = len(rows)
    variants_per_faq: dict[int, int] = {}
    for r in rows:
        variants_per_faq[r[2]] = variants_per_faq.get(r[2], 0) + 1

    print(f"FAQ 질문 {n}개 / FAQ {len(variants_per_faq)}개 · 임계값 {FAQ_THRESHOLD}\n")

    bad, weak, lonely = [], [], []
    for i, (qid, text, faq_id, answer) in enumerate(rows):
        best_same = best_other = -1.0
        other_faq = other_text = None
        for j, (qid2, text2, faq_id2, _a2) in enumerate(rows):
            if i == j:
                continue                      # leave-one-out
            s = sum(a * b for a, b in zip(vecs[i], vecs[j]))
            if faq_id2 == faq_id:
                best_same = max(best_same, s)
            elif s > best_other:
                best_other, other_faq, other_text = s, faq_id2, text2

        if variants_per_faq[faq_id] == 1:
            lonely.append((qid, text, faq_id, best_other, other_faq, other_text))
            continue

        margin = best_same - best_other
        if margin < 0:
            bad.append((qid, text, faq_id, best_same, best_other, other_faq, other_text))
        elif margin < MARGIN_WARN:
            weak.append((qid, text, faq_id, best_same, best_other, other_faq, other_text))

    if bad:
        print("✗ 점검 필요 — 다른 FAQ 변형이 더 가깝다")
        print("   차이가 크면(0.05+) 배치 오류일 가능성이 높고, 작으면 원래 인접한 주제일 수 있다.")
        print("   (실측 기준: 진짜 오분류였던 '학포 몇 학점부터'는 0.653 vs 0.761로 0.108 차이였다)")
        for qid, text, faq_id, bs, bo, of, ot in bad:
            gap = bo - bs
            tag = "배치 오류 의심" if gap >= MARGIN_WARN else "인접 주제일 수 있음"
            print(f"   q{qid} [FAQ {faq_id}] '{text}'  — {tag}")
            print(f"      같은 FAQ {bs:.3f}  <  FAQ {of} {bo:.3f} (차이 {gap:.3f})  ('{ot}')")
        print()

    if weak:
        print(f"! 경계 취약 — 차이 {MARGIN_WARN} 미만")
        for qid, text, faq_id, bs, bo, of, ot in weak:
            print(f"   q{qid} [FAQ {faq_id}] '{text}'  같은 {bs:.3f} / FAQ {of} {bo:.3f}")
        print()

    if lonely:
        print("· 변형 1개뿐 — 비교 불가(문제 아님). 다른 FAQ와 가까우면 참고만.")
        for qid, text, faq_id, bo, of, ot in lonely:
            flag = "  ← 다른 FAQ와 임계값 이상으로 유사" if bo >= FAQ_THRESHOLD else ""
            print(f"   q{qid} [FAQ {faq_id}] '{text}'  최근접 FAQ {of} {bo:.3f}{flag}")
        print()

    ok = n - len(bad) - len(weak) - len(lonely)
    print(f"정상 {ok} / 오분류 {len(bad)} / 취약 {len(weak)} / 단독 {len(lonely)}  (총 {n})")
    if bad:
        print("\n오분류가 있으면 faq_question.faq_id를 옳은 FAQ로 옮기고 서버를 재시작하세요"
              " (FAQ 인덱스는 기동 시 메모리로 만들어집니다).")


asyncio.run(main())
