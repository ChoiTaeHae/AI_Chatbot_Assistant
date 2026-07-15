"""
졸업 도메인 시드 스크립트 (idempotent)

학과(department) + 별칭(aliases) + 단과대학/학부(college/division) 계층 +
졸업요건(requirement_set/requirement_rule)을 한 번에 시딩한다.

- 여러 번 실행해도 안전(멱등): 스키마는 ADD COLUMN IF NOT EXISTS, 학과는 이름 기준 upsert,
  요건은 전체 삭제 후 재삽입.
- 이 프로젝트는 Alembic 미사용(create_all) → 기존 테이블 컬럼 추가는 이 스크립트가 ALTER로 처리.

실행:
    docker compose exec -w /app -e PYTHONPATH=/app backend python3 scripts/seed_graduation.py

주의:
- 계열(이공/인문)은 우송대 [별표1] 최소이수학점 기준 + 자체 판단(공학/컴퓨터/게임/철도/건축 및
  의약·보건계열 = 이공 126, 그 외 인문 120)을 반영. 정책 변경 시 ENGINEERING/SPECIAL 수정.
- 편입 요건(총 90/96 등)은 스키마에 편입 구분 필드가 없어 미반영(전원 신입학 기준).
"""
import asyncio
import re
from datetime import date

from sqlalchemy import select, text

from app.core.Database import engine, AsyncSessionLocal, Base
from app.models.DB_Table import Department, College, Division, RequirementSet, RequirementRule

# ──────────────────────────────────────────────────────────────
# 데이터: (단과대학, 학부, 학과) — 학부 None이면 단과대학 직속
# ──────────────────────────────────────────────────────────────
HIER = [
    (None, None, "자유전공학부"),
    ("솔브릿지국제경영대학", None, "솔브릿지경영학부"),
    ("엔디컷국제대학", None, "AI경영학과"),
    ("엔디컷국제대학", None, "AI·빅데이터학과"),
    ("엔디컷국제대학", None, "글로벌호스피탈리티학과"),
    ("철도대학", "철도건설시스템학부", "글로벌철도학과"),
    ("철도대학", "철도건설시스템학부", "철도건설시스템전공"),
    ("철도대학", "철도건설시스템학부", "건축공학전공"),
    ("철도대학", None, "철도경영학과"),
    ("철도대학", "철도시스템학부", "철도전기시스템전공"),
    ("철도대학", "철도시스템학부", "철도소프트웨어전공"),
    ("철도대학", None, "철도차량시스템학과"),
    ("철도대학", None, "철도자율전공"),
    ("소프트웨어(SW)융합대학", "테크노미디어융합학부", "글로벌미디어영상학과"),
    ("소프트웨어(SW)융합대학", "테크노미디어융합학부", "미디어디자인·영상전공"),
    ("소프트웨어(SW)융합대학", "게임멀티미디어학부", "게임소프트웨어전공"),
    ("소프트웨어(SW)융합대학", "게임멀티미디어학부", "게임그래픽전공"),
    ("소프트웨어(SW)융합대학", "소프트웨어학부", "컴퓨터공학전공"),
    ("소프트웨어(SW)융합대학", "소프트웨어학부", "컴퓨터·소프트웨어전공"),
    ("외식조리대학", "글로벌조리학부", "글로벌조리전공"),
    ("외식조리대학", "글로벌조리학부", "Lyfe조리전공"),
    ("외식조리대학", "외식조리학부", "글로벌외식,조리경영전공"),
    ("외식조리대학", "외식조리학부", "외식조리전공"),
    ("외식조리대학", "외식조리학부", "한식·조리과학전공"),
    ("외식조리대학", "외식조리학부", "외식,조리경영전공"),
    ("외식조리대학", "외식조리학부", "제과제빵·조리전공"),
    ("외식조리대학", None, "외식조리영양학과"),
    ("외식조리대학", None, "호텔관광경영학과"),
    ("외식조리대학", None, "외식조리자율전공"),
    ("보건복지대학", None, "사회복지학과"),
    ("보건복지대학", None, "작업치료학과"),
    ("보건복지대학", None, "언어치료·청각재활학과"),
    ("보건복지대학", None, "보건의료경영학과"),
    ("보건복지대학", None, "유아교육과"),
    ("보건복지대학", None, "뷰티디자인경영학과"),
    ("보건복지대학", None, "응급구조학과"),
    ("보건복지대학", None, "소방·안전학부"),
    ("보건복지대학", None, "간호학과"),
    ("보건복지대학", None, "물리치료학과"),
    ("보건복지대학", None, "스포츠건강재활학과"),
    ("보건복지대학", "동물관리학부", "동물의료관리학과"),
    ("보건복지대학", "동물관리학부", "토탈펫케어학과"),
    ("보건복지대학", None, "보건복지자율전공"),
]

# 기존 DB 학과 이름 → 공식명 (id/FK 유지한 채 rename)
RENAME = {
    "컴퓨터공학과": "컴퓨터공학전공",
    "컴퓨터/소프트웨어학과": "컴퓨터·소프트웨어전공",
    "AI빅데이터학과": "AI·빅데이터학과",
}

# 수동 약칭 보강 (옛 이름 포함)
MANUAL_ALIASES = {
    "컴퓨터공학전공": ["컴공", "컴퓨터공학", "컴퓨터공학과"],
    "컴퓨터·소프트웨어전공": ["컴소", "컴퓨터소프트웨어", "컴퓨터/소프트웨어학과", "소프트웨어학과"],
    "AI·빅데이터학과": ["ai빅데이터", "빅데이터", "AI빅데이터학과"],
    "철도소프트웨어전공": ["철소", "철도소프트웨어"],
    "철도차량시스템학과": ["철도차량", "철차"],
}

# ──────────────────────────────────────────────────────────────
# 졸업요건 수치 (우송대 [별표1] + 졸업학점 기준표)
# ──────────────────────────────────────────────────────────────
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# 일반학과 (교양, 전공) — 계열별. 2026만 계열 분리, 그 이전은 동일
GENERAL = {
    2026: {"인문": (31, 59), "이공": (34, 62)},
    2025: {"인문": (34, 62), "이공": (34, 62)},
    2024: {"인문": (37, 65), "이공": (37, 65)},
    2023: {"인문": (37, 65), "이공": (37, 65)},
    2022: {"인문": (37, 65), "이공": (37, 65)},
    2021: {"인문": (37, 65), "이공": (37, 65)},
    2020: {"인문": (37, 65), "이공": (37, 65)},
}

# 특수학과 (교양, 전공) — PDF 전용 행. 계열 무관(자기값)
SPECIAL = {
    "간호학과":             {2026:(20,88),2025:(20,88),2024:(25,89),2023:(25,89),2022:(22,85),2021:(22,85),2020:(22,85)},
    "작업치료학과":         {2026:(20,82),2025:(20,82),2024:(20,85),2023:(20,85),2022:(20,85),2021:(22,85),2020:(22,85)},
    "언어치료·청각재활학과": {2026:(20,82),2025:(20,82),2024:(19,85),2023:(19,85),2022:(16,85),2021:(22,85),2020:(22,85)},
    "스포츠건강재활학과":   {2026:(20,65),2025:(20,65),2024:(26,65),2023:(26,65),2022:(37,65),2021:(37,65),2020:(37,65)},
    "유아교육과":           {2026:(18,59),2025:(18,59),2024:(18,62),2023:(18,62),2022:(18,62),2021:(18,62),2020:(18,62)},
    "Lyfe조리전공":         {2026:(30,82),2025:(30,82),2024:(30,82),2023:(30,82),2022:(25,82),2021:(43,82),2020:(43,82)},
}

# 이공·예체능계열 (총 126). 나머지는 인문·사회 (총 120)
# = 공학/컴퓨터/게임/철도/건축 + AI빅데이터 + 의약·보건(간호/작업치료/언어치료/물리치료/응급구조/스포츠재활/동물의료)
ENGINEERING = {
    "컴퓨터공학전공", "컴퓨터·소프트웨어전공", "게임소프트웨어전공", "게임그래픽전공",
    "글로벌철도학과", "철도건설시스템전공", "건축공학전공", "철도경영학과",
    "철도전기시스템전공", "철도소프트웨어전공", "철도차량시스템학과", "철도자율전공",
    "AI·빅데이터학과",
    "간호학과", "작업치료학과", "언어치료·청각재활학과", "물리치료학과", "응급구조학과",
    "스포츠건강재활학과", "동물의료관리학과",
}
TOTAL = {"인문": 120, "이공": 126}


def gen_aliases(name: str) -> set[str]:
    al = set()
    base = re.sub(r"(전공|학과|학부|과)$", "", name)
    if base and base != name:
        al.add(base)
    for v in {name, base}:
        stripped = v.replace("·", "").replace("/", "").replace(",", "").replace(" ", "")
        if stripped:
            al.add(stripped)
    al.discard(name)
    al.discard("")
    return al


async def main():
    # ── 1. 스키마: 새 테이블 생성 + department 컬럼 추가 (멱등) ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # college/division 등 누락 테이블 생성
        await conn.execute(text("ALTER TABLE department ADD COLUMN IF NOT EXISTS aliases JSONB"))
        await conn.execute(text("ALTER TABLE department ADD COLUMN IF NOT EXISTS college_id INTEGER REFERENCES college(id)"))
        await conn.execute(text("ALTER TABLE department ADD COLUMN IF NOT EXISTS division_id INTEGER REFERENCES division(id)"))
    print("[1] 스키마 준비 완료 (college/division 테이블 + department 컬럼)")

    async with AsyncSessionLocal() as db:
        # ── 2. 학과 rename + upsert(+aliases) ──
        for old, new in RENAME.items():
            await db.execute(text("UPDATE department SET name=:new WHERE name=:old"), {"new": new, "old": old})
        await db.commit()

        existing = {d.name: d for d in (await db.execute(select(Department))).scalars()}
        for _, _, name in HIER:
            aliases = sorted(gen_aliases(name) | set(MANUAL_ALIASES.get(name, [])))
            if name in existing:
                existing[name].aliases = aliases
            else:
                d = Department(name=name, aliases=aliases)
                db.add(d)
                existing[name] = d
        await db.commit()
        print(f"[2] 학과 {len(HIER)}개 upsert 완료")

        # ── 3. college/division get-or-create + department 연결 ──
        colleges: dict[str, int] = {}
        for cname in sorted({c for c, _, _ in HIER if c}):
            row = (await db.execute(select(College).where(College.name == cname))).scalar_one_or_none()
            if not row:
                row = College(name=cname); db.add(row); await db.flush()
            colleges[cname] = row.id

        divisions: dict[tuple, int] = {}
        for c, d in sorted({(c, d) for c, d, _ in HIER if d}):
            row = (await db.execute(
                select(Division).where(Division.name == d, Division.college_id == colleges[c])
            )).scalar_one_or_none()
            if not row:
                row = Division(name=d, college_id=colleges[c]); db.add(row); await db.flush()
            divisions[(c, d)] = row.id

        for c, d, name in HIER:
            dep = existing[name]
            dep.college_id = colleges.get(c) if c else None
            dep.division_id = divisions.get((c, d)) if d else None
        await db.commit()
        print(f"[3] college {len(colleges)}개 / division {len(divisions)}개 연결 완료")

        # ── 4. 졸업요건: 전체 삭제 후 재삽입 ──
        await db.execute(text("DELETE FROM requirement_rule"))
        await db.execute(text("DELETE FROM requirement_set"))
        await db.commit()

        n = 0
        for _, _, name in HIER:
            dep = existing[name]
            gyeyeol = "이공" if name in ENGINEERING else "인문"
            total = TOTAL[gyeyeol]
            for y in YEARS:
                if name in SPECIAL:
                    lib, maj = SPECIAL[name][y]          # 특수학과: 자기값
                else:
                    lib, maj = GENERAL[y][gyeyeol]        # 일반학과: 계열별
                rs = RequirementSet(dept_id=dep.id, admission_year=y, valid_from=date(y, 3, 1))
                db.add(rs); await db.flush()
                db.add(RequirementRule(
                    set_id=rs.id, min_credits_major=maj, min_credits_liberal=lib,
                    min_credits_general=0, min_credits_total=total,
                ))
                n += 1
        await db.commit()
        print(f"[4] 졸업요건 {n}개 (학과 {len(HIER)} × 연도 {len(YEARS)}) 시딩 완료")
        print("\n✅ 졸업 도메인 시드 완료")


if __name__ == "__main__":
    asyncio.run(main())
