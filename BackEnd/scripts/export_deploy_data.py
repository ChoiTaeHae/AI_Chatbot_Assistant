"""배포용 데이터 내보내기 — 공용 DB/Qdrant → 파일.

수령자가 자기 PC에서 Postgres·Qdrant 컨테이너를 띄우고 이 파일들을 넣으면
공용 서버 없이도 똑같이 동작한다.

내보내는 것
  deploy/data/qdrant_points.jsonl   Qdrant 전체 포인트(dense+sparse 벡터 + payload)
  deploy/data/seed.sql              Postgres 참조 데이터 (INSERT 문)

개인정보는 내보내지 않는다. INCLUDE 목록에 있는 테이블만 나간다
(학생·성적·대화·피드백·미답변질문은 전부 제외).

실행 (컨테이너 안에서):
    docker compose exec backend python -m scripts.export_deploy_data
"""
import asyncio, json, base64
from pathlib import Path

from sqlalchemy import text

from app.core.Database import AsyncSessionLocal
from app.core.Qdrant import qdrant_client
from app.core.config import settings

OUT = Path("/app/scripts/_deploy_data")

# ── 내보낼 테이블 (참조·설정 데이터만) ────────────────────────────
#   순서 = INSERT 순서. 외래키 부모가 먼저 와야 한다.
INCLUDE = [
    "college", "division", "department", "course",
    "building", "room", "office", "building_contact",
    "requirement_set", "requirement_rule",
    "academic_schedule",
    "app_config", "search_dictionary",
    "topic",
    "faq", "faq_question",
    "document_file",
    "scholarship_catalog", "scholarship_file",
]

# ── 절대 내보내지 않는 테이블 (개인정보·운영 로그) ────────────────
EXCLUDE = [
    "student", "student_course", "student_achievement",
    "chat_log", "chat_session", "chat_message", "chat_feedback",
    "rewrite_label", "unanswered_question", "faq_notification",
    "token_blacklist",
]

BINARY_COLS = {("document_file", "content"), ("scholarship_file", "content")}

# 첨부파일 바이트는 SQL에 hex로 넣으면 용량이 2배가 된다(실측 293MB).
# 실제 파일로 빼고 seed.sql 에는 빈 bytea 를 넣은 뒤, import_files.py 가 채운다.
_files_manifest: list[dict] = []


def sql_literal(table: str, col: str, v) -> str:
    if v is None:
        return "NULL"
    if (table, col) in BINARY_COLS:
        return "''::bytea"          # 파일은 import_files.py 가 채운다
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "decode('" + bytes(v).hex() + "','hex')"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, dict)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


async def export_postgres() -> None:
    out = OUT / "seed.sql"
    total_rows = 0
    async with AsyncSessionLocal() as db:
        lines = [
            "-- 2조 SOL로몬 배포용 참조 데이터",
            "-- 개인정보(학생·성적·대화·미답변)는 포함하지 않는다.",
            "-- Postgres 컨테이너의 docker-entrypoint-initdb.d 에서 자동 실행된다.",
            "SET client_encoding = 'UTF8';",
            "",
        ]
        for tbl in INCLUDE:
            exists = (await db.execute(text(
                "SELECT to_regclass(:t)"), {"t": f"public.{tbl}"})).scalar()
            if not exists:
                print(f"  [건너뜀] {tbl} — 테이블 없음")
                continue
            res = await db.execute(text(f'SELECT * FROM "{tbl}" ORDER BY 1'))
            cols = list(res.keys())
            rows = res.fetchall()
            if not rows:
                print(f"  [비어있음] {tbl}")
                continue
            lines.append(f"-- {tbl} ({len(rows)} rows)")
            collist = ", ".join(f'"{c}"' for c in cols)
            for r in rows:
                row = dict(zip(cols, r))
                # 첨부파일은 실제 파일로 빼둔다
                for bcol in ("content",):
                    if (tbl, bcol) in BINARY_COLS and row.get(bcol) is not None:
                        blob = bytes(row[bcol])
                        rel = f"files/{tbl}/{row['id']}.bin"
                        p = OUT / rel
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(blob)
                        _files_manifest.append({
                            "table": tbl, "id": row["id"], "path": rel,
                            "filename": row.get("filename"), "size": len(blob)})
                vals = ", ".join(sql_literal(tbl, c, v) for c, v in zip(cols, r))
                lines.append(f'INSERT INTO "{tbl}" ({collist}) VALUES ({vals});')
            # 시퀀스 보정 (id 자동증가 테이블)
            if "id" in cols:
                lines.append(
                    f"SELECT setval(pg_get_serial_sequence('{tbl}','id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{tbl}\"),1), true);")
            lines.append("")
            total_rows += len(rows)
            print(f"  {tbl:24} {len(rows):5} rows")

        out.write_text("\n".join(lines), encoding="utf-8")

    (OUT / "files_manifest.json").write_text(
        json.dumps(_files_manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    fsize = sum(f["size"] for f in _files_manifest)
    print(f"\n  → {out}  ({out.stat().st_size/1024:.0f} KB, 총 {total_rows} rows)")
    print(f"  → files/  ({len(_files_manifest)}개, {fsize/1024/1024:.1f} MB)")
    print(f"  제외한 테이블: {', '.join(EXCLUDE)}")


def export_qdrant() -> None:
    coll = settings.active_collection
    out = OUT / "qdrant_points.jsonl"
    info = qdrant_client.get_collection(coll)
    print(f"  컬렉션 {coll}: {info.points_count} points")

    n, offset = 0, None
    with out.open("w", encoding="utf-8") as f:
        while True:
            points, offset = qdrant_client.scroll(
                collection_name=coll, limit=100,
                with_payload=True, with_vectors=True, offset=offset)
            if not points:
                break
            for p in points:
                vec = p.vector
                rec = {"id": p.id, "payload": p.payload, "vector": {}}
                if isinstance(vec, dict):
                    for name, v in vec.items():
                        if hasattr(v, "indices"):     # SparseVector
                            rec["vector"][name] = {
                                "indices": list(v.indices), "values": list(v.values)}
                        else:
                            rec["vector"][name] = list(v)
                else:
                    rec["vector"] = list(vec)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            if offset is None:
                break
    print(f"  → {out}  ({out.stat().st_size/1024/1024:.1f} MB, {n} points)")

    # 컬렉션 설정도 함께 저장 (수령자가 같은 스펙으로 생성해야 함)
    cfg = info.config.params
    spec = {
        "collection": coll,
        "vectors": {k: {"size": v.size, "distance": str(v.distance)}
                    for k, v in (cfg.vectors or {}).items()} if isinstance(cfg.vectors, dict) else None,
        "sparse_vectors": list((cfg.sparse_vectors or {}).keys()) if cfg.sparse_vectors else [],
    }
    (OUT / "qdrant_schema.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {OUT/'qdrant_schema.json'}")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("1) Qdrant 내보내기")
    print("=" * 60)
    export_qdrant()
    print()
    print("=" * 60)
    print("2) PostgreSQL 참조 데이터 내보내기")
    print("=" * 60)
    await export_postgres()


if __name__ == "__main__":
    asyncio.run(main())
