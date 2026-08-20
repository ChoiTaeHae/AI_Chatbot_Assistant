"""배포용 데이터 반입 — 파일 → 로컬 Postgres/Qdrant.

export_deploy_data.py 가 만든 deploy/data/ 를 읽어 빈 DB와 빈 Qdrant를 채운다.
컨테이너를 처음 띄운 뒤 한 번만 실행하면 된다.

실행 (프로젝트 루트에서):
    docker compose exec backend python3 -m scripts.import_deploy_data

이미 데이터가 있으면 아무것도 하지 않는다(중복 방지). 강제로 다시 넣으려면:
    docker compose exec backend python3 -m scripts.import_deploy_data --force
"""
import argparse, asyncio, json, sys
from pathlib import Path

from qdrant_client import models
from sqlalchemy import text

from app.core.Database import AsyncSessionLocal, engine, Base
from app.core.Qdrant import qdrant_client
from app.core.config import settings
# create_all 은 '임포트된' 모델만 만든다. 이 줄이 없으면 Base.metadata 가 비어
# 테이블이 하나도 생성되지 않는다(실측: relation "department" does not exist).
from app.models import DB_Table  # noqa: F401

DATA = Path("/app/deploy_data")
BATCH = 100


# ── 1. 테이블 생성 ────────────────────────────────────────────────
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  테이블 생성/확인 완료")


# ── 2. 참조 데이터 ────────────────────────────────────────────────
async def load_seed(force: bool) -> None:
    sql_path = DATA / "seed.sql"
    if not sql_path.exists():
        print(f"  [건너뜀] {sql_path} 없음")
        return

    async with AsyncSessionLocal() as db:
        n = (await db.execute(text('SELECT COUNT(*) FROM "department"'))).scalar()
        if n and not force:
            print(f"  [건너뜀] 이미 데이터 있음 (department {n}행). --force 로 재실행 가능")
            return
        if force:
            # 자식→부모 역순으로 비운다
            for t in ["scholarship_file", "scholarship_catalog", "faq_question", "faq",
                      "requirement_rule", "requirement_set", "building_contact", "office",
                      "room", "building", "course", "department", "division", "college",
                      "academic_schedule", "search_dictionary", "app_config", "topic",
                      "document_file"]:
                try:
                    await db.execute(text(f'TRUNCATE "{t}" CASCADE'))
                except Exception:
                    pass
            await db.commit()
            print("  기존 참조 데이터 삭제")

        # 줄 단위로 읽어 주석·빈 줄을 먼저 걷어낸 뒤 ';' 로 문장을 맺는다.
        # 통째로 ";\n" 으로 split 하면 '-- college (6 rows)' 같은 헤더 주석이 다음
        # INSERT 와 한 덩어리가 되어, 주석으로 시작한다는 이유로 그 INSERT 까지
        # 버려진다(실측: college id=1 유실 → division FK 위반).
        stmts, buf = [], []
        for line in sql_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("--"):
                continue
            buf.append(s)
            if s.endswith(";"):
                stmts.append(" ".join(buf)[:-1])
                buf = []
        if buf:
            stmts.append(" ".join(buf))

        ok, failed = 0, 0
        for s in stmts:
            # 문장마다 SAVEPOINT — 하나가 실패해도 나머지가 밀리지 않는다.
            try:
                async with db.begin_nested():
                    await db.execute(text(s))
                ok += 1
            except Exception as e:
                failed += 1
                if failed <= 5:      # 처음 5건만 출력 (로그 폭주 방지)
                    print(f"  [실패] {s[:80]}...\n         → {type(e).__name__}: {str(e)[:160]}")
        await db.commit()
        print(f"  참조 데이터 {ok}/{len(stmts)} 문장 적용" +
              (f" (실패 {failed}건)" if failed else ""))


# ── 3. 첨부파일 ───────────────────────────────────────────────────
async def load_files() -> None:
    man = DATA / "files_manifest.json"
    if not man.exists():
        print("  [건너뜀] files_manifest.json 없음")
        return
    items = json.loads(man.read_text(encoding="utf-8"))
    async with AsyncSessionLocal() as db:
        n = 0
        for it in items:
            p = DATA / it["path"]
            if not p.exists():
                print(f"  [없음] {it['path']}")
                continue
            await db.execute(
                text(f'UPDATE "{it["table"]}" SET content = :c WHERE id = :i'),
                {"c": p.read_bytes(), "i": it["id"]})
            n += 1
        await db.commit()
        print(f"  첨부파일 {n}/{len(items)}개 적재")


# ── 4. Qdrant ─────────────────────────────────────────────────────
def load_qdrant(force: bool) -> None:
    schema_path = DATA / "qdrant_schema.json"
    points_path = DATA / "qdrant_points.jsonl"
    if not points_path.exists():
        print(f"  [건너뜀] {points_path} 없음")
        return

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    coll = settings.active_collection
    if coll != schema["collection"]:
        print(f"  [주의] .env 컬렉션({coll}) != 내보낸 컬렉션({schema['collection']})")

    exists = qdrant_client.collection_exists(coll)
    if exists and not force:
        cnt = qdrant_client.get_collection(coll).points_count
        if cnt:
            print(f"  [건너뜀] 이미 {cnt} points 있음. --force 로 재생성 가능")
            return
    if exists and force:
        qdrant_client.delete_collection(coll)
        print("  기존 컬렉션 삭제")
        exists = False

    if not exists:
        qdrant_client.create_collection(
            collection_name=coll,
            vectors_config={
                name: models.VectorParams(size=v["size"],
                                          distance=models.Distance.COSINE)
                for name, v in schema["vectors"].items()},
            sparse_vectors_config={
                name: models.SparseVectorParams()
                for name in schema.get("sparse_vectors", [])},
        )
        print(f"  컬렉션 생성: {coll}")

    # 검색 필터에 쓰는 payload 인덱스
    for field in ("topic", "source", "doc_date", "file_name"):
        try:
            qdrant_client.create_payload_index(
                collection_name=coll, field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD)
        except Exception:
            pass
    print("  payload 인덱스 생성 (topic, source, doc_date, file_name)")

    buf, total = [], 0
    with points_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            vec = {}
            for name, v in rec["vector"].items():
                if isinstance(v, dict) and "indices" in v:
                    vec[name] = models.SparseVector(indices=v["indices"],
                                                    values=v["values"])
                else:
                    vec[name] = v
            buf.append(models.PointStruct(id=rec["id"], vector=vec,
                                          payload=rec["payload"]))
            if len(buf) >= BATCH:
                qdrant_client.upsert(collection_name=coll, points=buf)
                total += len(buf); buf = []
                print(f"    {total} points ...", end="\r")
    if buf:
        qdrant_client.upsert(collection_name=coll, points=buf)
        total += len(buf)
    print(f"  포인트 {total}개 적재 완료          ")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="기존 데이터를 지우고 다시 넣는다")
    args = ap.parse_args()

    if not DATA.exists():
        sys.exit(f"데이터 폴더가 없습니다: {DATA}\n"
                 f"docker-compose.yml 의 ./deploy/data 마운트를 확인하세요.")

    print("=" * 60); print("1) 테이블 생성"); print("=" * 60)
    await create_tables()
    print()
    print("=" * 60); print("2) 참조 데이터"); print("=" * 60)
    await load_seed(args.force)
    print()
    print("=" * 60); print("3) 첨부파일"); print("=" * 60)
    await load_files()
    print()
    print("=" * 60); print("4) Qdrant"); print("=" * 60)
    load_qdrant(args.force)
    print("\n완료. http://localhost:5173 에서 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
