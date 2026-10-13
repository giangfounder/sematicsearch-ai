"""Rerank listwise bằng Gemini (structured output). Chỉ chấp nhận product_id đã gửi."""
from __future__ import annotations

from app.catalog.index import DemoIndex
from app.gemini.pool import BaseGemini
from app.search.prompts import RERANK_SYSTEM, rerank_contents, rerank_schema


def constraint_texts(constraints) -> list[str]:
    return [f"{c.desc} ({'nói rõ' if c.explicit else 'mong muốn'})" for c in constraints]


def build_request(idx: DemoIndex, query: str, constraints, cands: list[dict]) -> tuple[str, dict, list[int]]:
    top = cands[: idx.scoring["rerank_top"]]
    ids = [c["product_id"] for c in top]
    lines = [(c["product_id"], idx.rerank_lines[c["i"]]) for c in top]
    return rerank_contents(query, constraint_texts(constraints), lines), rerank_schema(ids), ids


async def rerank(gem: BaseGemini, idx: DemoIndex, contents: str, schema: dict, ids: list[int], *,
                 model: str, timeout_ms: int) -> dict:
    return await gem.generate_json(
        system=RERANK_SYSTEM, contents=contents, schema=schema, call_type="rerank", timeout_ms=timeout_ms,
        demo_id=idx.demo_id, model=model, max_output_tokens=120 + 90 * len(ids))


def parse_rerank(raw: dict, allowed: set[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in (raw or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        try:
            pid = int(r.get("product_id"))
            rel = float(r.get("relevance"))
        except (TypeError, ValueError):
            continue
        if pid not in allowed or pid in out:
            continue
        reason = r.get("reason") if isinstance(r.get("reason"), str) else ""
        out[pid] = {"relevance": min(1.0, max(0.0, rel)),
                    "satisfies_constraints": bool(r.get("satisfies_constraints", True)),
                    "reason": reason.strip()[:300]}
    return out
