"""Ablation (chạy tay, không chạy trong CI): đo hit@1/hit@3/status/latency khi bật dần / tắt từng thành phần.
python -m scripts.ablation --demo dienmay [--split test] [--configs B0,B1,...] [--concurrency 2]
Kết quả: reports/ablation_<demo>_<split>.md + .json"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.catalog.index import IndexManager
from app.config import get_settings
from app.db import create_pool, migrate
from app.evals.evaluate import evaluate
from app.gemini.pool import make_gemini
from app.search.pipeline import BASELINE_FLAGS, DEFAULT_FLAGS, SearchService

REPORTS = Path(__file__).resolve().parent.parent / "reports"

B = dict(BASELINE_FLAGS)
STEPS: list[tuple[str, str, dict, str]] = []


def _add(name: str, desc: str, change: dict, mode: str = "fast") -> None:
    B.update(change)
    STEPS.append((name, desc, dict(B), mode))


_add("B0", "Baseline như bản cũ: LLM tách lọc -> lọc cứng -> cosine Int8 1 vector (profile)", {})
_add("B1", "+ đa vector (name/profile/use_case/question, max theo kind)", {"multi_vector": True})
_add("B2", "+ BM25 có dấu/không dấu + RRF + điểm tổng hợp", {"bm25": True, "baseline": False, "composite": True})
_add("B3", "+ entity linking + rule parser + ứng viên vào prompt", {"entity": True, "rules": True, "entity_in_prompt": True})
_add("B4", "+ lọc cứng chỉ explicit, ràng buộc mềm, nới điều kiện", {"soft_filter": True, "relax": True})
_add("B5", "+ chấm lại cosine float32", {"float_rescore": True})
_add("B6", "+ ngữ cảnh nhiều lượt", {"context": True})
_add("B7", "+ rerank Gemini (gating auto)", {"rerank": True}, "auto")
STEPS.append(("B7-acc", "rerank luôn bật (mode accurate)", dict(DEFAULT_FLAGS), "accurate"))
for key, label in [("multi_vector", "đa vector"), ("bm25", "BM25"), ("entity", "entity"), ("soft_filter", "lọc mềm"),
                   ("float_rescore", "rescore f32")]:
    STEPS.append((f"-{key}", f"Full (auto) bỏ {label}", {**DEFAULT_FLAGS, key: False}, "auto"))


def fmt(x, pct=True):
    if x is None:
        return "-"
    return f"{x * 100:.1f}%" if pct else f"{x:.0f}"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--configs", default="")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    s = get_settings()
    pool = await create_pool(s.database_url)
    await migrate(pool)
    gem = make_gemini(s)
    await gem.start()
    idx = IndexManager(pool)
    await idx.reload(args.demo)
    svc = SearchService(s, gem, idx, pool)
    rows, full = [], {}
    want = set(args.configs.split(",")) if args.configs else None
    try:
        for name, desc, flags, mode in STEPS:
            if want and name not in want:
                continue
            t0 = time.time()
            marks = set()

            async def prog(p, name=name, marks=marks):
                step = int(p // 25)
                if step not in marks:
                    marks.add(step)
                    print(f"  {name} {p:.0f}%", flush=True)

            rep = await evaluate(svc, pool, args.demo, split=args.split, mode=mode, flags=flags,
                                 concurrency=args.concurrency, progress=prog)
            lat = rep["latency_ms"]
            row = {"config": name, "desc": desc, "mode": mode, "n": rep["n_cases"], "hit@1": rep["hit@1"],
                   "hit@3": rep["hit@3"], "mrr": rep["mrr"], "status_acc": rep["status_accuracy"],
                   "matched_wrong": rep["matched_wrong_rate"], "matched_wrong_ci95": rep["matched_wrong_ci95"],
                   "rerank_rate": rep["rerank_rate"], "fallback_rate": rep["fallback_rate"],
                   "p50_total": (lat.get("total") or {}).get("p50"), "p95_total": (lat.get("total") or {}).get("p95"),
                   "p95_understand": (lat.get("understand") or {}).get("p95"), "p95_embed": (lat.get("embed") or {}).get("p95"),
                   "p95_rerank": (lat.get("rerank") or {}).get("p95"), "by_category": rep["by_category"]}
            rows.append(row)
            full[name] = rep
            print(f"{name:8s} hit@1={fmt(row['hit@1'])} hit@3={fmt(row['hit@3'])} status={fmt(row['status_acc'])} "
                  f"matched_wrong={fmt(row['matched_wrong'])} rerank={fmt(row['rerank_rate'])} "
                  f"fallback={fmt(row['fallback_rate'])} p95={row['p95_total']}ms ({time.time() - t0:.0f}s)", flush=True)
    finally:
        REPORTS.mkdir(exist_ok=True)
        out = REPORTS / f"ablation_{args.demo}_{args.split}"
        out.with_suffix(".json").write_text(json.dumps({"rows": rows, "reports": full}, ensure_ascii=False, indent=1,
                                                       default=str), encoding="utf-8")
        md = [f"# Ablation {args.demo} (split={args.split})", "",
              "| Cấu hình | Mô tả | hit@1 | hit@3 | MRR | Status đúng | Matched sai | Rerank | Fallback | p50 | p95 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            md.append(f"| {r['config']} | {r['desc']} | {fmt(r['hit@1'])} | {fmt(r['hit@3'])} | {fmt(r['mrr'])} | "
                      f"{fmt(r['status_acc'])} | {fmt(r['matched_wrong'])} | {fmt(r['rerank_rate'])} | "
                      f"{fmt(r['fallback_rate'])} | {r['p50_total']} | {r['p95_total']} |")
        out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"-> {out}.md")
        await gem.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
