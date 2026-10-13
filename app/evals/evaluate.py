"""Chạy toàn bộ eval_cases của demo qua pipeline thật (không cache response; embedding/understanding dùng
cache bền để chạy lại rẻ) và tính chỉ số."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict

from app import repo
from app.evals.metrics import pct, wilson
from app.search.pipeline import SearchService

STATUSES = ["matched", "ambiguous", "no_match", "out_of_scope"]


async def run_cases(svc: SearchService, slug: str, cases: list[dict], *, mode: str, flags: dict | None,
                    concurrency: int, progress=None, retry_wait_s: float = 30.0) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    fl = dict(flags or {})
    if fl.get("persistent_cache") is None:  # evaluate luôn dùng cache bền để chạy lại rẻ
        fl["persistent_cache"] = True
    done = 0
    results: list[dict | None] = [None] * len(cases)

    async def one(i: int, c: dict):
        nonlocal done
        async with sem:
            for attempt in range(4):
                resp = await svc.search(slug, {"text": c["query"], "top_k": 3, "mode": mode,
                                               "context": c.get("context"), "debug": True}, flags=fl, use_cache=False)
                fb = resp.get("fallback_reason") or ""
                if "quota_exhausted" in fb:
                    raise RuntimeError(f"Dừng evaluate: Gemini hết quota ngày ({fb}). Số đo sẽ sai nếu chạy tiếp.")
                # 429 là giới hạn quota (free tier), không phải hành vi hệ thống -> chờ rồi đo lại câu đó
                if "rate_limited" not in fb or attempt == 3:
                    break
                await asyncio.sleep(retry_wait_s)
        results[i] = {"case": c, "resp": resp}
        done += 1
        if progress:
            await progress(100.0 * done / len(cases))

    await asyncio.gather(*(one(i, c) for i, c in enumerate(cases)))
    return [r for r in results if r is not None]


def ranked_ids(resp: dict) -> list[int]:
    return [c["product_id"] for c in (resp.get("debug") or {}).get("candidates") or []]


def summarize(results: list[dict], with_failures: bool = True) -> dict:
    n = len(results)
    prod = [r for r in results if r["case"]["expected_product_ids"]]
    hit1 = hit3 = 0
    rr = 0.0
    conf: dict = {s: Counter() for s in STATUSES}
    status_ok = 0
    matched = matched_wrong = 0
    reranked = fallback = 0
    lat: dict[str, list[float]] = defaultdict(list)
    by_cat: dict = defaultdict(lambda: {"n": 0, "hit1": 0, "status_ok": 0, "n_prod": 0})
    failures, miss_by_product = [], Counter()
    for r in results:
        c, resp = r["case"], r["resp"]
        exp = set(c["expected_product_ids"])
        ids = ranked_ids(resp)
        top1 = ids[0] if ids and resp["status"] != "out_of_scope" else None
        cat = by_cat[c.get("category") or "other"]
        cat["n"] += 1
        h1 = False
        if exp:
            cat["n_prod"] += 1
            h1 = top1 in exp
            hit1 += h1
            hit3 += bool(set(ids[:3]) & exp) and resp["status"] != "out_of_scope"
            cat["hit1"] += h1
            for k, pid in enumerate(ids[:10]):
                if pid in exp and resp["status"] != "out_of_scope":
                    rr += 1 / (k + 1)
                    break
        ok = resp["status"] == c["expected_status"]
        status_ok += ok
        cat["status_ok"] += ok
        conf[c["expected_status"]][resp["status"]] += 1
        if resp["status"] == "matched":
            matched += 1
            if top1 not in exp:
                matched_wrong += 1
        reranked += resp["reranked"]
        fallback += bool(resp["fallback_reason"])
        for k, v in resp["latency_ms"].items():
            if k != "rerank" or resp["reranked"]:
                lat[k].append(v)
        if (exp and not h1) or not ok:
            for pid in exp:
                if not h1:
                    miss_by_product[pid] += 1
            if with_failures:
                failures.append({
                    "case_id": c.get("id"), "query": c["query"], "context": c.get("context"),
                    "category": c.get("category"), "expected_ids": sorted(exp),
                    "expected_status": c["expected_status"], "status": resp["status"],
                    "got_ids": ids[:3], "understanding": resp["understanding"],
                    "relaxed_keys": resp["relaxed_keys"], "fallback_reason": resp["fallback_reason"],
                    "debug": (resp.get("debug") or {}).get("candidates", [])[:5],
                })
    np_ = len(prod)
    lo, hi = wilson(matched_wrong, matched)
    return {
        "n_cases": n, "n_product_cases": np_,
        "hit@1": round(hit1 / np_, 4) if np_ else None,
        "hit@3": round(hit3 / np_, 4) if np_ else None,
        "mrr": round(rr / np_, 4) if np_ else None,
        "status_accuracy": round(status_ok / n, 4) if n else None,
        "matched_wrong_rate": round(matched_wrong / matched, 4) if matched else 0.0,
        "matched_wrong_ci95": [round(lo, 4), round(hi, 4)],
        "matched_wrong": matched_wrong, "matched": matched,
        "rerank_rate": round(reranked / n, 4) if n else 0.0,
        "fallback_rate": round(fallback / n, 4) if n else 0.0,
        "confusion": {k: dict(v) for k, v in conf.items()},
        "latency_ms": {k: {"p50": pct(v, 50), "p95": pct(v, 95)} for k, v in lat.items()},
        "by_category": {k: {"n": v["n"], "hit@1": round(v["hit1"] / v["n_prod"], 3) if v["n_prod"] else None,
                            "status_acc": round(v["status_ok"] / v["n"], 3)} for k, v in sorted(by_cat.items())},
        "failures": failures,
        "_miss_by_product": dict(miss_by_product),
    }


async def evaluate(svc: SearchService, pool, slug: str, *, split: str = "test", mode: str = "auto",
                   flags: dict | None = None, concurrency: int = 4, progress=None, keep_raw: bool = False) -> dict:
    demo = await repo.get_demo(pool, slug)
    cases = await repo.list_eval_cases(pool, demo["id"], split)
    results = await run_cases(svc, slug, cases, mode=mode, flags=flags, concurrency=concurrency, progress=progress)
    rep = summarize(results)
    idx = svc.indexes.get(slug)
    names = {p["id"]: p["name"] for p in idx.products} if idx else {}
    miss = rep.pop("_miss_by_product")
    rep["suggestions"] = [
        {"product_id": pid, "name": names.get(pid), "misses": k,
         "hint": "thêm alias/câu hỏi mẫu gần với các câu sai bên dưới",
         "failed_queries": [f["query"] for f in rep["failures"] if pid in f["expected_ids"]][:5]}
        for pid, k in sorted(miss.items(), key=lambda kv: -kv[1]) if k >= 2]
    rep.update({"slug": slug, "split": split, "mode": mode, "flags": flags or {}, "data_version": idx.version if idx else None})
    if keep_raw:
        rep["_results"] = results
    return rep
