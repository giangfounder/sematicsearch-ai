"""Truy cập dữ liệu. Search nóng KHÔNG dùng module này (chỉ dùng cache RAM)."""
from __future__ import annotations

from typing import Any

import asyncpg

from app.db import bump_version

PRODUCT_CORE = ["sku", "name", "category", "brand", "price", "price_unit", "in_stock",
                "short_description", "description", "attributes", "aliases", "use_cases",
                "sample_questions", "enrichment_status", "extra", "raw"]
DEF_FIELDS = ["key", "label", "type", "unit", "unit_aliases", "label_aliases", "enum_values",
              "filterable", "searchable", "weight", "display_order"]


def _d(r) -> dict | None:
    return dict(r) if r is not None else None


# ---------------- demos ----------------
async def lock_demo(conn, demo_id: int) -> None:
    # All catalog writers lock the parent first, in the same order as embedding
    # checkpoints. This also serializes overlapping replace imports.
    if not await conn.fetchval("SELECT id FROM demos WHERE id=$1 FOR UPDATE", demo_id):
        raise ValueError("bảng dữ liệu đã bị xóa")


async def get_demo(db, slug: str) -> dict | None:
    return _d(await db.fetchrow("SELECT * FROM demos WHERE slug=$1", slug))


async def get_demo_by_id(db, demo_id: int) -> dict | None:
    return _d(await db.fetchrow("SELECT * FROM demos WHERE id=$1", demo_id))


async def list_demos(db, account_id: int | None = None) -> list[dict]:
    where = "" if account_id is None else "WHERE d.account_id=$1 OR d.account_id IS NULL"
    args = [] if account_id is None else [account_id]
    rows = await db.fetch(f"""SELECT d.*, (SELECT count(*) FROM products p WHERE p.demo_id=d.id) AS n_products,
                             (SELECT count(*) FROM eval_cases e WHERE e.demo_id=d.id AND e.active) AS n_eval
                             FROM demos d {where} ORDER BY d.id""", *args)
    return [dict(r) for r in rows]


async def create_demo(db, data: dict) -> dict:
    return _d(await db.fetchrow(
        """INSERT INTO demos(slug, name, industry, embed_model, embed_dim, thresholds, settings, account_id)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        data["slug"], data["name"], data.get("industry"), data.get("embed_model", "gemini-embedding-001"),
        data.get("embed_dim", 768), data.get("thresholds") or {}, data.get("settings") or {}, data.get("account_id")))


async def update_demo(pool: asyncpg.Pool, demo_id: int, data: dict) -> dict:
    allowed = {k: v for k, v in data.items() if k in ("name", "industry", "thresholds", "settings")}
    async with pool.acquire() as conn, conn.transaction():
        await lock_demo(conn, demo_id)
        if allowed:
            sets = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(allowed))
            await conn.execute(f"UPDATE demos SET {sets} WHERE id=$1", demo_id, *allowed.values())
        await bump_version(conn, demo_id)
        return _d(await conn.fetchrow("SELECT * FROM demos WHERE id=$1", demo_id))


async def delete_demo(db, demo_id: int) -> None:
    await db.execute("DELETE FROM demos WHERE id=$1", demo_id)


# ---------------- definitions ----------------
async def list_defs(db, demo_id: int) -> list[dict]:
    rows = await db.fetch("SELECT * FROM attribute_definitions WHERE demo_id=$1 ORDER BY display_order, id", demo_id)
    return [dict(r) for r in rows]


async def upsert_defs(conn, demo_id: int, defs: list[dict], replace: bool = False) -> None:
    await lock_demo(conn, demo_id)
    if replace:
        keys = [d["key"] for d in defs]
        await conn.execute("DELETE FROM attribute_definitions WHERE demo_id=$1 AND NOT (key = ANY($2::text[]))",
                           demo_id, keys)
    for i, d in enumerate(defs):
        await conn.execute(
            """INSERT INTO attribute_definitions(demo_id, key, label, type, unit, unit_aliases, label_aliases,
                   enum_values, filterable, searchable, weight, display_order)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (demo_id, key) DO UPDATE SET label=EXCLUDED.label, type=EXCLUDED.type,
                   unit=EXCLUDED.unit, unit_aliases=EXCLUDED.unit_aliases, label_aliases=EXCLUDED.label_aliases,
                   enum_values=EXCLUDED.enum_values, filterable=EXCLUDED.filterable,
                   searchable=EXCLUDED.searchable, weight=EXCLUDED.weight, display_order=EXCLUDED.display_order""",
            demo_id, d["key"], d.get("label") or d["key"], d.get("type", "text"), d.get("unit"),
            d.get("unit_aliases") or [], d.get("label_aliases") or [], d.get("enum_values") or [],
            bool(d.get("filterable", False)), bool(d.get("searchable", True)), float(d.get("weight", 0.5)),
            int(d.get("display_order", i)))


async def delete_def(db, demo_id: int, key: str) -> None:
    await lock_demo(db, demo_id)
    await db.execute("DELETE FROM attribute_definitions WHERE demo_id=$1 AND key=$2", demo_id, key)


# ---------------- products ----------------
async def list_products(db, demo_id: int) -> list[dict]:
    rows = await db.fetch("SELECT * FROM products WHERE demo_id=$1 ORDER BY id", demo_id)
    return [dict(r) for r in rows]


async def get_product(db, demo_id: int, pid: int) -> dict | None:
    return _d(await db.fetchrow("SELECT * FROM products WHERE demo_id=$1 AND id=$2", demo_id, pid))


async def upsert_products(conn, demo_id: int, rows: list[dict], mode: str = "upsert") -> dict[str, int]:
    """mode: upsert (giữ sản phẩm không có trong file) | replace (xoá sản phẩm không có trong file).
    Trả map sku -> id."""
    await lock_demo(conn, demo_id)
    if mode == "replace":
        await conn.execute("DELETE FROM products WHERE demo_id=$1 AND NOT (sku = ANY($2::text[]))",
                           demo_id, [r["sku"] for r in rows])
    out: dict[str, int] = {}
    for r in rows:
        vals = [r.get(k) for k in PRODUCT_CORE]
        vals[PRODUCT_CORE.index("in_stock")] = True if r.get("in_stock") is None else bool(r.get("in_stock"))
        for k in ("attributes", "extra", "raw"):
            vals[PRODUCT_CORE.index(k)] = r.get(k) or {}
        for k in ("aliases", "use_cases", "sample_questions"):
            vals[PRODUCT_CORE.index(k)] = list(r.get(k) or [])
        vals[PRODUCT_CORE.index("enrichment_status")] = r.get("enrichment_status") or "none"
        cols = ", ".join(PRODUCT_CORE)
        ph = ", ".join(f"${i + 2}" for i in range(len(PRODUCT_CORE)))
        upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in PRODUCT_CORE if c != "sku")
        pid = await conn.fetchval(
            f"""INSERT INTO products(demo_id, {cols}) VALUES($1, {ph})
                ON CONFLICT (demo_id, sku) DO UPDATE SET {upd}, updated_at=now() RETURNING id""",
            demo_id, *vals)
        out[r["sku"]] = pid
    return out


async def patch_product(conn, demo_id: int, pid: int, data: dict) -> dict | None:
    await lock_demo(conn, demo_id)
    allowed = {k: v for k, v in data.items() if k in PRODUCT_CORE}
    if not allowed:
        return await get_product(conn, demo_id, pid)
    sets = ", ".join(f"{k}=${i + 3}" for i, k in enumerate(allowed))
    return _d(await conn.fetchrow(f"UPDATE products SET {sets}, updated_at=now() WHERE demo_id=$1 AND id=$2 RETURNING *",
                                  demo_id, pid, *allowed.values()))


async def delete_product(conn, demo_id: int, pid: int) -> None:
    await lock_demo(conn, demo_id)
    await conn.execute("DELETE FROM products WHERE demo_id=$1 AND id=$2", demo_id, pid)


# ---------------- vectors ----------------
async def list_vectors(db, demo_id: int) -> list[dict]:
    rows = await db.fetch(
        """SELECT v.product_id, v.kind, v.source_text, v.text_hash, v.embed_model, v.vec_int8, v.scale, v.vec_f32
           FROM product_vectors v JOIN products p ON p.id=v.product_id WHERE p.demo_id=$1 ORDER BY v.id""", demo_id)
    return [dict(r) for r in rows]


async def existing_hashes(db, demo_id: int) -> set[tuple[int, str, str]]:
    rows = await db.fetch("""SELECT v.product_id, v.kind, v.text_hash FROM product_vectors v
                             JOIN products p ON p.id=v.product_id WHERE p.demo_id=$1""", demo_id)
    return {(r["product_id"], r["kind"], r["text_hash"]) for r in rows}


async def replace_vectors(conn, demo_id: int, keep: set[tuple[int, str, str]], new_rows: list[dict]) -> int:
    """Xoá vector không còn trong `keep`, thêm vector mới.

    Embed chạy lâu (rate-limit) nên sản phẩm có thể bị nhập lại/xoá trong lúc chờ. Bỏ qua vector
    của sản phẩm đã biến mất (tránh vi phạm khoá ngoại) và không xoá vector của sản phẩm mới thêm
    sau khi embed bắt đầu (id mới không nằm trong `keep`).
    """
    cur = await existing_hashes(conn, demo_id)
    snapshot_pids = {pid for pid, _, _ in keep}
    stale = [c for c in cur if c not in keep and c[0] in snapshot_pids]
    for pid, kind, h in stale:
        await conn.execute("DELETE FROM product_vectors WHERE product_id=$1 AND kind=$2 AND text_hash=$3", pid, kind, h)
    await add_vectors(conn, demo_id, new_rows)
    return len(stale)


async def add_vectors(conn, demo_id: int, new_rows: list[dict]) -> int:
    """Append a completed batch without removing any earlier checkpoints."""
    if new_rows:
        live = {r["id"] for r in await conn.fetch("SELECT id FROM products WHERE demo_id=$1 FOR KEY SHARE", demo_id)}
        rows = [(r["product_id"], r["kind"], r["source_text"], r["text_hash"], r["embed_model"], r["vec_int8"],
                 r["scale"], r["vec_f32"]) for r in new_rows if r["product_id"] in live]
        if rows:
            await conn.executemany(
                """INSERT INTO product_vectors(product_id, kind, source_text, text_hash, embed_model, vec_int8, scale, vec_f32)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (product_id, kind, text_hash) DO NOTHING""",
                rows)
        return len(rows)
    return 0


# ---------------- eval cases ----------------
async def list_eval_cases(db, demo_id: int, split: str | None = None, active_only: bool = True) -> list[dict]:
    q = "SELECT * FROM eval_cases WHERE demo_id=$1"
    args: list[Any] = [demo_id]
    if split and split != "all":
        q += " AND split=$2"
        args.append(split)
    if active_only:
        q += " AND active"
    rows = await db.fetch(q + " ORDER BY id", *args)
    return [dict(r) for r in rows]


async def insert_eval_cases(db, demo_id: int, cases: list[dict]) -> int:
    await db.executemany(
        """INSERT INTO eval_cases(demo_id, query, context, expected_product_ids, expected_status, category, split, source)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
        [(demo_id, c["query"], c.get("context"), list(c.get("expected_product_ids") or []), c["expected_status"],
          c.get("category"), c.get("split", "test"), c.get("source", "manual")) for c in cases])
    return len(cases)


async def delete_eval_cases(db, demo_id: int, source: str | None = None) -> None:
    if source:
        await db.execute("DELETE FROM eval_cases WHERE demo_id=$1 AND source=$2", demo_id, source)
    else:
        await db.execute("DELETE FROM eval_cases WHERE demo_id=$1", demo_id)


# ---------------- jobs ----------------
async def create_job(db, job_id: str, demo_id: int | None, kind: str, params: dict) -> None:
    await db.execute("INSERT INTO jobs(id, demo_id, kind, status, params) VALUES($1,$2,$3,'queued',$4)",
                     job_id, demo_id, kind, params)


async def update_job(db, job_id: str, **fields) -> None:
    sets = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(fields))
    await db.execute(f"UPDATE jobs SET {sets}, updated_at=now() WHERE id=$1", job_id, *fields.values())


async def get_job(db, job_id: str) -> dict | None:
    return _d(await db.fetchrow("SELECT * FROM jobs WHERE id=$1", job_id))


async def list_jobs(db, demo_id: int | None = None, limit: int = 50) -> list[dict]:
    if demo_id:
        rows = await db.fetch("SELECT id, demo_id, kind, status, progress, error, created_at, updated_at FROM jobs WHERE demo_id=$1 ORDER BY created_at DESC LIMIT $2", demo_id, limit)
    else:
        rows = await db.fetch("SELECT id, demo_id, kind, status, progress, error, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


# ---------------- logs & usage ----------------
LOG_COLS = ["demo_id", "request_id", "text", "context", "understanding", "candidates", "status", "product_ids",
            "reranked", "cache_hit", "fallback_reason", "latency", "data_version"]


async def insert_logs(db, rows: list[dict]) -> None:
    ph = ", ".join(f"${i + 1}" for i in range(len(LOG_COLS)))
    await db.executemany(f"INSERT INTO search_logs({', '.join(LOG_COLS)}) VALUES({ph}) ON CONFLICT (request_id) DO NOTHING",
                         [tuple(r.get(c) for c in LOG_COLS) for r in rows])


async def get_log(db, request_id: str) -> dict | None:
    return _d(await db.fetchrow("SELECT * FROM search_logs WHERE request_id=$1", request_id))


async def set_feedback(db, request_id: str, feedback: dict) -> bool:
    r = await db.execute("UPDATE search_logs SET feedback=$2 WHERE request_id=$1", request_id, feedback)
    return r.endswith("1")


async def flush_usage(db, pending: dict) -> None:
    if not pending:
        return
    await db.executemany(
        """INSERT INTO gemini_usage(day, demo_id, call_type, model, calls, input_tokens, output_tokens, errors)
           VALUES(current_date,$1,$2,$3,$4,$5,$6,$7)
           ON CONFLICT (day, demo_id, call_type, model) DO UPDATE SET calls=gemini_usage.calls+EXCLUDED.calls,
             input_tokens=gemini_usage.input_tokens+EXCLUDED.input_tokens,
             output_tokens=gemini_usage.output_tokens+EXCLUDED.output_tokens,
             errors=gemini_usage.errors+EXCLUDED.errors""",
        [(d, ct, m, c, i, o, e) for (d, ct, m), (c, i, o, e) in pending.items()])


async def usage_by_demo(db, days: int = 30) -> list[dict]:
    rows = await db.fetch("""SELECT d.slug, u.call_type, u.model, sum(u.calls) calls, sum(u.input_tokens) input_tokens,
                                    sum(u.output_tokens) output_tokens, sum(u.errors) errors
                             FROM gemini_usage u LEFT JOIN demos d ON d.id=u.demo_id
                             WHERE u.day >= current_date - $1::int GROUP BY 1,2,3 ORDER BY 1,2""", days)
    return [dict(r) for r in rows]
