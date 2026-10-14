"""Ghi vector phải chịu được việc sản phẩm bị xoá/nhập lại trong lúc embed (không vỡ khoá ngoại)."""
from __future__ import annotations

from app import repo
from app.db import create_pool, migrate


def _vec(pid: int, kind: str, h: str) -> dict:
    return {"product_id": pid, "kind": kind, "source_text": f"{kind}:{h}", "text_hash": h,
            "embed_model": "fake", "vec_int8": b"\x01", "scale": 1.0, "vec_f32": None}


async def test_replace_vectors_skips_products_removed_mid_embed(db_url):
    pool = await create_pool(db_url)
    await migrate(pool)
    did = (await repo.create_demo(pool, {"slug": "v", "name": "V"}))["id"]

    async with pool.acquire() as conn, conn.transaction():
        ids = await repo.upsert_products(conn, did, [{"sku": "A", "name": "A"}, {"sku": "B", "name": "B"}],
                                         mode="replace")

    keep = {(ids["A"], "name", "ha"), (ids["B"], "name", "hb")}
    new_rows = [_vec(ids["A"], "name", "ha"), _vec(ids["B"], "name", "hb")]

    async with pool.acquire() as conn, conn.transaction():
        await repo.upsert_products(conn, did, [{"sku": "A", "name": "A"}], mode="replace")
        removed = await repo.replace_vectors(conn, did, keep, new_rows)

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT product_id FROM product_vectors WHERE product_id = ANY($1::int[])",
                                [ids["A"], ids["B"]])
    assert {r["product_id"] for r in rows} == {ids["A"]}
    assert removed == 0
    await pool.close()


async def test_replace_vectors_keeps_vectors_of_reimported_product(db_url):
    pool = await create_pool(db_url)
    await migrate(pool)
    did = (await repo.create_demo(pool, {"slug": "v2", "name": "V2"}))["id"]

    async with pool.acquire() as conn, conn.transaction():
        first = await repo.upsert_products(conn, did, [{"sku": "A", "name": "A"}], mode="replace")
    keep_snapshot = {(first["A"], "name", "ha")}

    async with pool.acquire() as conn, conn.transaction():
        await repo.upsert_products(conn, did, [], mode="replace")
        await repo.upsert_products(conn, did, [{"sku": "A", "name": "A"}], mode="replace")
        new_id = (await repo.list_products(conn, did))[0]["id"]
        await repo.replace_vectors(conn, did, {(new_id, "name", "ha")}, [_vec(new_id, "name", "ha")])
    assert new_id != first["A"]

    async with pool.acquire() as conn, conn.transaction():
        await repo.replace_vectors(conn, did, keep_snapshot, [])

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT product_id FROM product_vectors WHERE product_id = ANY($1::int[])",
                                [first["A"], new_id])
    assert {r["product_id"] for r in rows} == {new_id}
    await pool.close()
