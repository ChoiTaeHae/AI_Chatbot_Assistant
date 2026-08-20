"""실운영 답변율 측정 — 누적 대화 로그에서 '답하지 못한' 비율을 집계한다.

논문 4장 수치용. 판정 기준은 서비스와 동일하게 faq_service.is_unanswered 를 쓴다
(답변 첫 문단에 '찾지 못' 계열 표현이 있으면 미답변).

실행:
    docker compose exec backend python3 -m scripts.answer_rate
"""
import asyncio
from sqlalchemy import text

from app.core.Database import AsyncSessionLocal
from app.services.faq_service import is_unanswered


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT content, source
            FROM chat_message
            WHERE role = 'assistant' AND content IS NOT NULL AND content <> ''
        """))).all()

    total = len(rows)
    unans = sum(1 for c, s in rows if is_unanswered(c, s))
    ans = total - unans

    print("=" * 56)
    print(f"  누적 답변 수      {total:,}")
    print(f"  답변 성공         {ans:,}")
    print(f"  미답변(유보)      {unans:,}")
    print(f"  답변율            {ans / total * 100:.1f}%")
    print("=" * 56)

    # 출처별 분해 — FAQ 원문 반환 / RAG 생성 / 결정적 처리기
    async with AsyncSessionLocal() as db:
        by_src = (await db.execute(text("""
            SELECT COALESCE(source, '(없음)') AS src, COUNT(*) AS n
            FROM chat_message
            WHERE role = 'assistant' AND content IS NOT NULL AND content <> ''
            GROUP BY 1 ORDER BY 2 DESC
        """))).all()
    print("  출처별 분포 (상위 8)")
    for src, n in by_src[:8]:
        print(f"    {src:<20} {n:>6,}  ({n / total * 100:4.1f}%)")

    # 월별 추이 — 초기 개발 중 로그가 섞여 있어 전체 평균은 현재 성능을 과소평가한다.
    async with AsyncSessionLocal() as db:
        months = (await db.execute(text("""
            SELECT to_char(created_at, 'YYYY-MM') AS ym, content, source
            FROM chat_message
            WHERE role = 'assistant' AND content IS NOT NULL AND content <> ''
            ORDER BY created_at
        """))).all()

    agg: dict[str, list[int]] = {}
    for ym, c, s in months:
        a = agg.setdefault(ym, [0, 0])
        a[0] += 1
        if is_unanswered(c, s):
            a[1] += 1

    print()
    print("  월별 답변율")
    for ym in sorted(agg):
        n, u = agg[ym]
        print(f"    {ym}   {n - u:>5,} / {n:>5,}   {(n - u) / n * 100:5.1f}%")

    # 최근 1,000건 — '현재 상태'에 가장 가까운 지표
    recent = months[-1000:]
    ru = sum(1 for _, c, s in recent if is_unanswered(c, s))
    print()
    print(f"  최근 {len(recent):,}건 답변율   {(len(recent) - ru) / len(recent) * 100:.1f}%"
          f"  (미답변 {ru}건)")


if __name__ == "__main__":
    asyncio.run(main())
