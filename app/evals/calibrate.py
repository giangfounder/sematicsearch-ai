"""Dò ngưỡng tối ưu trên split=dev: chạy pipeline 1 lần ở mode=accurate (có đủ điểm trước & sau rerank),
fit Platt (A,B), rồi mô phỏng gating + quyết định cho lưới ngưỡng, không gọi thêm Gemini."""
from __future__ import annotations

import itertools
import math

import numpy as np

from app import repo
from app.config import DEFAULT_THRESHOLDS
from app.evals.evaluate import run_cases
from app.evals.metrics import fit_platt, wilson
from app.search.scoring import effective_weights, raw_score


def _sig(x):
    return 1 / (1 + math.exp(-max(-50.0, min(50.0, x))))


def _prep(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        c, resp = r["case"], r["resp"]
        ents = (resp["understanding"].get("entities") or {}).get("products") or []
        exact = [e["product_id"] for e in ents if e["match"] == "exact" and e["score"] >= 0.9]
        cands = [{"pid": d["product_id"], "raw": d["raw"] or 0.0, "rel": d.get("rerank"),
                  "sat": d.get("rerank_sat", True), "cos": (d.get("dense") or {}).get("cos_f32"),
                  "rrf": d.get("rrf") or 0.0, "entity": d.get("entity") or 0.0, "soft": d.get("soft") or 0.0,
                  "stock": d.get("stock") or 0.0, "prev": d.get("prev") or 0.0}
                 for d in (resp.get("debug") or {}).get("candidates") or []]
        has_dense = "embed_" not in (resp.get("fallback_reason") or "")
        out.append({"exp": set(c["expected_product_ids"]), "exp_status": c["expected_status"],
                    "oos": resp["status"] == "out_of_scope", "exact": exact[0] if len(exact) == 1 else None,
                    "cands": cands, "has_dense": has_dense})
    return out


def fit_cos_range(cases: list[dict]) -> tuple[float, float] | None:
    """cos_lo ~ trung vị cosine của ứng viên SAI, cos_hi ~ phân vị 75 của ứng viên ĐÚNG."""
    pos = [x["cos"] for c in cases for x in c["cands"] if x.get("cos") is not None and x["pid"] in c["exp"]]
    neg = [x["cos"] for c in cases for x in c["cands"] if x.get("cos") is not None and x["pid"] not in c["exp"]]
    if len(pos) < 5 or len(neg) < 5:
        return None
    lo, hi = float(np.percentile(neg, 50)), float(np.percentile(pos, 75))
    if hi - lo < 0.05:
        return None
    return round(lo, 4), round(hi, 4)


def recompute_raw(cases: list[dict], a: dict, lo: float, hi: float) -> None:
    for c in cases:
        w = effective_weights(a, c.get("has_dense", True))
        for x in c["cands"]:
            if "rrf" in x:
                x["raw"], _ = raw_score(x, w, lo, hi)


def simulate(cases: list[dict], th: dict, beta: float, penalty: float) -> dict:
    ok = matched = wrong = rr = hit1 = nprod = 0
    for c in cases:
        if c["exp"]:
            nprod += 1
        if c["oos"]:
            ok += c["exp_status"] == "out_of_scope"
            continue
        cs = [(x["pid"], _sig(th["platt_a"] * x["raw"] + th["platt_b"]), x["rel"], x["sat"]) for x in c["cands"]]
        cs.sort(key=lambda t: -t[1])
        if not cs:
            ok += c["exp_status"] == "no_match"
            continue
        f1 = cs[0][1]
        f2 = cs[1][1] if len(cs) > 1 else 0.0
        gated_off = (c["exact"] is not None and cs[0][0] == c["exact"]) or (f1 >= th["gate_high"] and f1 - f2 >= th["gate_margin"])
        if not gated_off and any(t[2] is not None for t in cs):
            rr += 1
            sc = []
            for pid, f, rel, sat in cs:
                s = (1 - beta) * f + beta * (rel if rel is not None else 0.3)
                sc.append((pid, s * (1 if sat else penalty)))
        else:
            sc = [(pid, f) for pid, f, _, _ in cs]
        sc.sort(key=lambda t: -t[1])
        s1 = sc[0][1]
        s2 = sc[1][1] if len(sc) > 1 else 0.0
        if s1 < th["t_min"]:
            st = "no_match"
        elif s1 >= th["t_match"] and (s1 - s2 >= th["margin"] or (c["exact"] is not None and sc[0][0] == c["exact"])):
            st = "matched"
        else:
            st = "ambiguous"
        ok += st == c["exp_status"]
        top1_ok = sc[0][0] in c["exp"]
        hit1 += bool(c["exp"]) and top1_ok
        if st == "matched":
            matched += 1
            wrong += not top1_ok
    n = len(cases)
    return {"status_acc": ok / n if n else 0, "matched": matched, "matched_wrong": wrong,
            "matched_wrong_rate": wrong / matched if matched else 0.0, "rerank_rate": rr / n if n else 0,
            "hit@1": hit1 / nprod if nprod else None, "status_ok": ok}


def search_thresholds(cases: list[dict], beta_grid=(0.4, 0.6, 0.8), max_wrong_rate: float = 0.02,
                      penalty: float = 0.6, base: dict | None = None, weights: dict | None = None) -> dict:
    cos_range = fit_cos_range(cases) if weights else None
    if cos_range:
        recompute_raw(cases, weights, *cos_range)
    raws, ys = [], []
    for c in cases:
        if c["oos"] or not c["cands"]:
            continue
        top = max(c["cands"], key=lambda x: x["raw"])
        raws.append(top["raw"])
        ys.append(int(top["pid"] in c["exp"]))
    A, B = fit_platt(raws, ys)
    th = {**DEFAULT_THRESHOLDS, **(base or {}), "platt_a": round(A, 4), "platt_b": round(B, 4)}
    if cos_range:
        th["cos_lo"], th["cos_hi"] = cos_range
    best = None
    # Bước 1: luôn rerank (gating tắt) -> chọn beta + ngưỡng quyết định
    always = {"gate_high": 2.0, "gate_margin": 2.0}
    for beta, t_match, t_min, margin in itertools.product(
            beta_grid, np.arange(0.45, 0.96, 0.05), np.arange(0.15, 0.61, 0.05), (0.02, 0.05, 0.08, 0.12, 0.16)):
        if t_min >= t_match:
            continue
        cand = {**th, **always, "t_match": round(float(t_match), 2), "t_min": round(float(t_min), 2), "margin": margin,
                "margin_amb": round(margin + 0.04, 2)}
        m = simulate(cases, cand, beta, penalty)
        if m["matched_wrong_rate"] > max_wrong_rate:
            continue
        key = (m["status_ok"], m["matched"], -abs(t_match - 0.7))
        if best is None or key > best[0]:
            best = (key, cand, beta, m)
    if best is None:  # không đạt ràng buộc -> chọn ít sai nhất
        cand = {**th, **always, "t_match": 0.95, "t_min": 0.5, "margin": 0.16, "margin_amb": 0.2}
        best = ((0,), cand, 0.6, simulate(cases, cand, 0.6, penalty))
    _, cand, beta, m_always = best
    # Bước 2: gating — giảm số lần rerank mà không mất câu đúng
    gate_best = (cand["gate_high"], cand["gate_margin"], m_always)
    for gh, gm in itertools.product((0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95), (0.05, 0.1, 0.15, 0.2, 0.3)):
        m = simulate(cases, {**cand, "gate_high": gh, "gate_margin": gm}, beta, penalty)
        if m["status_ok"] >= m_always["status_ok"] and m["matched_wrong_rate"] <= max_wrong_rate:
            if m["rerank_rate"] < gate_best[2]["rerank_rate"]:
                gate_best = (gh, gm, m)
    cand = {**cand, "gate_high": gate_best[0], "gate_margin": gate_best[1]}
    final = simulate(cases, cand, beta, penalty)
    lo, hi = wilson(final["matched_wrong"], final["matched"])
    final["matched_wrong_ci95"] = [round(lo, 4), round(hi, 4)]
    return {"thresholds": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in cand.items()},
            "rerank_beta": beta, "dev_metrics": final, "n_cases": len(cases),
            "platt_fit": {"n": len(raws), "positives": int(sum(ys))}}


async def calibrate(svc, pool, slug: str, *, concurrency: int = 4, save: bool = True, progress=None) -> dict:
    demo = await repo.get_demo(pool, slug)
    cases = await repo.list_eval_cases(pool, demo["id"], "dev")
    if len(cases) < 10:
        raise ValueError("cần >= 10 eval_cases split=dev để calibrate")
    results = await run_cases(svc, slug, cases, mode="accurate", flags=None, concurrency=concurrency, progress=progress)
    prepped = _prep(results)
    current = simulate(prepped, {**DEFAULT_THRESHOLDS, **(demo.get("thresholds") or {})},
                       ((demo.get("settings") or {}).get("scoring") or {}).get("rerank_beta", 0.6), 0.6)
    idx = svc.indexes.get(slug)
    out = search_thresholds(prepped, base=demo.get("thresholds"), weights=idx.scoring["a"] if idx else None)
    out["dev_metrics_before"] = current
    if save:
        settings = dict(demo.get("settings") or {})
        scoring = dict(settings.get("scoring") or {})
        scoring["rerank_beta"] = out["rerank_beta"]
        settings["scoring"] = scoring
        await repo.update_demo(pool, demo["id"], {"thresholds": out["thresholds"], "settings": settings})
        out["saved"] = True
    return out
