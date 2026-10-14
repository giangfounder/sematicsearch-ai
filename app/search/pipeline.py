"""Luồng online: chuẩn hoá -> cache -> entity + rule -> gather(understand, embed) -> retrieve -> score
-> gating -> rerank -> quyết định -> response (+ log bất đồng bộ)."""
from __future__ import annotations

import asyncio
import copy
import time
import uuid

import numpy as np

from app.catalog.index import DemoIndex, IndexManager, bm25_tokens
from app.config import Settings
from app.gemini.pool import BaseGemini, GeminiError
from app.search import retrieve as R
from app.search.cache import AsyncTTL, PersistentCache, hkey
from app.search.rerank import build_request, parse_rerank, rerank
from app.search.rules import parse_rules
from app.search.scoring import (apply_rerank, clarify_question, composite, confidence, decide, need_rerank,
                                template_reason)
from app.search.understand import build_llm_request, merge_filters, resolve_mentioned, validate_llm
from app.text.normalize import normalize_query, norm_text, strip_accents
from app.text.vn_numbers import spoken_to_digits

DEFAULT_FLAGS = {
    "understand": True, "rules": True, "multi_vector": True, "bm25": True, "entity": True,
    "entity_in_prompt": True, "soft_filter": True, "relax": True, "float_rescore": True,
    "composite": True, "context": True, "rerank": True, "baseline": False,
    "embed_rewritten": None, "persistent_cache": None, "soft_deadline_ms": None, "concurrent_rerank": True, "entity_fastpath": True,
}

BASELINE_FLAGS = {**DEFAULT_FLAGS, "rules": False, "multi_vector": False, "bm25": False, "entity": False,
                  "entity_in_prompt": False, "soft_filter": False, "relax": False, "float_rescore": False,
                  "composite": False, "context": False, "rerank": False, "baseline": True, "concurrent_rerank": False, "entity_fastpath": False}

DATA_HIDE = {"id", "demo_id", "sku", "name", "price", "price_unit", "in_stock", "attributes", "updated_at",
             "sample_questions", "enrichment_status"}


class NotFound(Exception):
    pass


def _jaccard(a: str, b: str) -> float:
    x, y = set(strip_accents(a).split()), set(strip_accents(b).split())
    return len(x & y) / max(1, len(x | y))


def public_filters(f: dict) -> dict:
    return {
        "price": f.get("price"), "category": f.get("category"), "brand": f.get("brand"),
        "in_stock": f.get("in_stock"),
        "attributes": [{k: a.get(k) for k in ("key", "op", "value", "value_max", "explicit")} for a in f.get("attributes") or []],
    }


def merge_previous(prev: dict | None, cur: dict) -> dict:
    """Lượt tinh chỉnh: lấy bộ lọc lượt trước làm nền, điều kiện mới ghi đè theo key."""
    if not prev:
        return cur
    out = copy.deepcopy(cur)
    if not out.get("price") and prev.get("price"):
        out["price"] = prev["price"]
    for k in ("category", "brand"):
        if not out.get(k) and prev.get(k):
            out[k], out[f"{k}_explicit"] = prev[k], bool(prev.get(f"{k}_explicit", True))
    if out.get("in_stock") is None:
        out["in_stock"] = prev.get("in_stock")
    have = {a["key"] for a in out.get("attributes") or []}
    for a in prev.get("attributes") or []:
        if a.get("key") not in have:
            out.setdefault("attributes", []).append(dict(a))
    return out


class SearchService:
    def __init__(self, settings: Settings, gem: BaseGemini, indexes: IndexManager, pool=None, log_sink=None):
        self.s = settings
        self.gem = gem
        self.indexes = indexes
        self.persist = PersistentCache(pool)
        self.log_sink = log_sink  # callable(dict)
        self.resp_cache = AsyncTTL(settings.cache_size, settings.response_cache_ttl)
        self.und_cache = AsyncTTL(settings.cache_size, settings.understand_cache_ttl)
        self.emb_cache = AsyncTTL(settings.cache_size, settings.embed_cache_ttl)
        self._bg: set[asyncio.Task] = set()
        indexes.on_swap.append(lambda _slug: self.resp_cache.clear())

    # ------------------------------------------------------------------ helpers
    async def _embed(self, idx: DemoIndex, text: str, persist: bool) -> np.ndarray:
        key = hkey("emb", idx.embed_model, idx.demo["embed_dim"], text)

        async def compute():
            if persist:
                v = await self.persist.get_vec(key)
                if v is not None:
                    return v
            v = (await self.gem.embed([text], "RETRIEVAL_QUERY", call_type="embed_query",
                                      timeout_ms=self.s.embed_timeout_ms, demo_id=idx.demo_id,
                                      model=idx.embed_model, dim=idx.demo["embed_dim"]))[0]
            if persist:
                await self.persist.put_vec(key, v)
            return v

        v, _ = await self.emb_cache.get_or_compute(key, compute)
        return v

    async def _understand(self, idx: DemoIndex, text: str, ctx: dict | None, cand_names: list[str], persist: bool) -> dict:
        system, contents, schema = build_llm_request(idx, text, ctx, cand_names)
        model = self.s.gemini_llm_model
        key = hkey("und", model, hkey(system, schema), contents)

        async def compute():
            if persist:
                v = await self.persist.get_json(key)
                if v is not None:
                    return v
            v = await self.gem.generate_json(system=system, contents=contents, schema=schema, call_type="understand",
                                             timeout_ms=self.s.understand_timeout_ms, demo_id=idx.demo_id,
                                             model=model, max_output_tokens=500)
            if persist:
                await self.persist.put_json(key, v)
            return v

        v, _ = await self.und_cache.get_or_compute(key, compute)
        return v

    async def _rerank(self, idx: DemoIndex, query: str, constraints, cands: list[dict], persist: bool) -> dict:
        contents, schema, ids = build_request(idx, query, constraints, cands)
        model = self.s.gemini_rerank_model
        key = hkey("rr", model, contents)

        async def compute():
            if persist:
                v = await self.persist.get_json(key)
                if v is not None:
                    return v
            v = await rerank(self.gem, idx, contents, schema, ids, model=model, timeout_ms=self.s.rerank_timeout_ms)
            if persist:
                await self.persist.put_json(key, v)
            return v

        raw, _ = await self.und_cache.get_or_compute(key, compute)
        return parse_rerank(raw, set(ids))

    @staticmethod
    async def _timed(coro):
        t0 = time.perf_counter()
        try:
            return await coro, None, (time.perf_counter() - t0) * 1000
        except GeminiError as e:
            return None, e.reason, (time.perf_counter() - t0) * 1000

    # ------------------------------------------------------------------ main
    async def search(self, slug: str, req: dict, flags: dict | None = None, use_cache: bool = True) -> dict:
        t_start = time.perf_counter()
        idx = self.indexes.get(slug)
        if idx is None:
            raise NotFound(slug)
        fl = {**DEFAULT_FLAGS, **(flags or {})}
        if fl["embed_rewritten"] is None:
            fl["embed_rewritten"] = self.s.embed_rewritten
        persist = self.s.persistent_cache_online if fl["persistent_cache"] is None else bool(fl["persistent_cache"])
        text = (req.get("text") or "").strip()
        top_k = max(1, min(int(req.get("top_k") or 3), 10))
        mode = req.get("mode") or "auto"
        debug = bool(req.get("debug"))
        ctx = (req.get("context") or None) if fl["context"] else None
        request_id = uuid.uuid4().hex

        text_norm, _ = normalize_query(text, idx.fillers)
        ctx_key = None
        if ctx:
            ctx_key = [norm_text(ctx.get("previous_text") or ""), sorted(ctx.get("previous_product_ids") or []),
                       ctx.get("previous_filters")]
        flag_key = {k: v for k, v in fl.items() if v != DEFAULT_FLAGS.get(k)}
        rkey = hkey(slug, idx.version, text_norm, ctx_key, top_k, mode, debug, flag_key)
        if use_cache:
            hit = self.resp_cache.get(rkey)
            if hit is not None:
                resp = copy.deepcopy(hit)
                resp["request_id"] = request_id
                resp["cache_hit"] = True
                resp["latency_ms"] = {"total": round((time.perf_counter() - t_start) * 1000, 2),
                                      "understand": 0.0, "embed": 0.0, "retrieve": 0.0, "rerank": 0.0}
                self._log(idx, request_id, text, ctx, resp, None)
                return resp

        resp, log_extra = await self._search(idx, text, text_norm, ctx, top_k, mode, debug, fl, persist, request_id, t_start)
        if use_cache and resp.get("fallback_reason") is None:
            self.resp_cache.set(rkey, copy.deepcopy(resp))
        self._log(idx, request_id, text, ctx, resp, log_extra)
        return resp

    async def _search(self, idx, text, text_norm, ctx, top_k, mode, debug, fl, persist, request_id, t_start):
        lat = {"understand": 0.0, "embed": 0.0, "retrieve": 0.0, "rerank": 0.0}
        fallback: list[str] = []

        # (c) entity + rule parser: cục bộ, vài ms
        digits_text = spoken_to_digits(text_norm, idx.units)
        ent = idx.entity.match(strip_accents(digits_text)) if fl["entity"] or fl["rules"] else None
        if fl["rules"]:
            rules = parse_rules(text_norm, idx.defs, ent, idx.units)
            rules.pop("_digits_text", None)
        else:
            rules = {"price": None, "attributes": []}
        ent_products = ent.products if (ent and fl["entity"]) else {}

        cand_names: list[str] = []
        if fl["entity_in_prompt"]:
            # thứ tự: entity khớp mạnh trước, rồi BM25 trên trường tên
            order = [idx.pid2i[pid] for pid, _h in sorted(ent_products.items(), key=lambda kv: -kv[1]["score"])]
            bm = idx.bm25_name.scores(bm25_tokens(digits_text))
            order += [int(i) for i in np.argsort(-bm, kind="stable")[:20] if bm[i] > 0]
            cand_names = [idx.products[i]["name"] for i in dict.fromkeys(order)][:20]

        # Đường tắt: khách gọi đúng tên/mã 1 sản phẩm (entity khớp chính xác, không phải lượt tiếp nối) ->
        # bỏ qua gọi LLM hiểu câu VÀ rerank, trả bằng rule + embedding (~600ms). Entity exact có độ chính xác cao.
        fast_entity = (fl.get("entity_fastpath", True) and fl["understand"] and fl["entity"] and not ctx
                       and ent is not None and ent.exact_unique is not None and not fl["baseline"])

        # (a) + (b) song song
        t_par = time.perf_counter()
        und_task = (asyncio.create_task(self._timed(self._understand(idx, text, ctx, cand_names, persist)))
                    if fl["understand"] and not fast_entity else None)
        qvec, err, lat["embed"] = await self._timed(self._embed(idx, text_norm, persist))
        if err:
            fallback.append(f"embed_{err}")
        # Rerank song song với hiểu câu: entity linking + rule đã chạy cục bộ nên có thể truy xuất suy đoán
        # và khởi động rerank ngay khi có embedding, thay vì chờ hiểu câu xong mới rerank (tiết kiệm ~1,3s).
        ent_brands = ent.brands if ent else []
        ent_cats = ent.categories if ent else []
        rr_task = None
        # chỉ khởi động rerank nếu ngân sách còn đủ cho nó kịp (tránh tốn quota LLM cho call sẽ bị cắt,
        # và tránh làm nặng rate-limit khiến hiểu câu chậm theo). deadline chặt -> auto chạy như fast.
        dl = fl.get("deadline_ms", self.s.search_deadline_ms)
        rerank_fits = (not dl) or (dl / 1000 - (time.perf_counter() - t_start) >= self.s.rerank_expected_ms / 1000)
        if (fl.get("concurrent_rerank", True) and fl["rerank"] and mode != "fast" and und_task is not None
                and not fl["baseline"] and qvec is not None and rerank_fits):
            spec_filters = merge_filters(None, rules, ent_brands, ent_cats, idx)
            spec_rt = R.retrieve(idx, qvec=qvec, texts=[digits_text], filters=spec_filters, intent="find_product",
                                 ctx=ctx, ent_products=ent_products, flags=fl)
            composite(idx, spec_rt.candidates, has_dense=True, flags=fl)
            spec_exact = ent.exact_unique if (ent and fl["entity"]) else None
            if need_rerank(idx, spec_rt.candidates, mode, spec_exact, fl)[0] and spec_rt.candidates:
                rr_task = asyncio.create_task(self._timed(
                    self._rerank(idx, text, spec_rt.constraints, spec_rt.candidates, persist)))

        # Ngân sách thời gian còn lại tới hạn chót tổng (bảo đảm tổng < deadline_ms). None = không giới hạn.
        deadline_ms = fl.get("deadline_ms", self.s.search_deadline_ms)

        def budget_s(reserve_ms: float = 0.0):
            if not deadline_ms:
                return None
            return deadline_ms / 1000 - (time.perf_counter() - t_start) - reserve_ms / 1000

        raw_llm = None
        if und_task is not None:
            soft = fl.get("soft_deadline_ms") or self.s.understand_soft_deadline_ms
            # Ưu tiên hiểu câu (ảnh hưởng độ chính xác) hơn rerank: cho hiểu câu gần hết ngân sách.
            # Rerank chỉ được áp nếu nó tình cờ xong song song trong phần còn lại (hiếm khi <2s).
            wait = budget_s(20.0)
            if soft and not ctx:
                wait = soft / 1000 if wait is None else min(wait, soft / 1000)
            und_res = None
            if wait is None:
                und_res = await und_task
            else:
                done, _ = await asyncio.wait({und_task}, timeout=max(0.0, wait))
                und_res = und_task.result() if done else None
            if und_res is None:
                fallback.append("understand_deferred")
                lat["understand"] = round((time.perf_counter() - t_par) * 1000, 1)
                self._bg.add(und_task)
                und_task.add_done_callback(self._bg.discard)
            else:
                raw_llm, err, lat["understand"] = und_res
                if err:
                    fallback.append(f"understand_{err}")

        llm = validate_llm(raw_llm, idx) if raw_llm is not None else None
        intent = llm["intent"] if llm else "find_product"
        rewritten = (llm or {}).get("rewritten_query") or ""
        said_something = bool(ent_products or (ent and (ent.brands or ent.categories))
                              or (rules.get("price") and any(k in rules["price"] for k in ("min", "max", "approx")))
                              or any(a.get("explicit") for a in rules.get("attributes") or []))
        if intent in ("out_of_scope", "chitchat") and said_something:
            intent = "find_product"
        if llm is None and ctx and ctx.get("previous_product_ids") and not ent_products:
            intent = "refine_previous"

        if fl["baseline"]:
            filters = merge_filters(llm, {"price": None, "attributes": []}, [], [], idx)
            # baseline giống bản cũ: hãng/category LLM nói ra là lọc cứng
            filters["brand_explicit"] = bool(filters.get("brand"))
            filters["category_explicit"] = bool(filters.get("category"))
        else:
            filters = merge_filters(llm, rules, ent_brands, ent_cats, idx)
        if intent == "refine_previous" and ctx and ctx.get("previous_filters"):
            filters = merge_previous(ctx["previous_filters"], filters)

        # boost sản phẩm khách gọi đích danh (LLM trích mentioned_products) nếu khớp chắc chắn và chưa có entity
        mentioned = (llm or {}).get("mentioned_products") or []
        if mentioned and fl["entity"] and not fl["baseline"]:
            for pid, sc in resolve_mentioned(mentioned, idx).items():
                cur = ent_products.get(pid)
                if cur is None or cur["score"] < sc:
                    ent_products[pid] = {"score": sc, "match": "mentioned", "surface": ""}

        understanding = {
            "intent": intent, "rewritten_query": rewritten or None, "filters": public_filters(filters),
            "entities": ent.to_dict() if ent else None,
            "mentioned_products": (llm or {}).get("mentioned_products") or [],
        }
        if llm and llm.get("dropped"):
            understanding["dropped"] = llm["dropped"]
        if fast_entity:
            understanding["fastpath"] = "entity_exact"

        if intent in ("out_of_scope", "chitchat"):
            # lưới an toàn: LLM có thể từ chối nhầm câu hỏi theo nhu cầu ("đi hàn quốc dùng gói nào").
            # Truy xuất cục bộ không tốn API; chỉ ghi đè khi có embedding và ứng viên đạt ngưỡng tin cậy.
            probe = None
            if qvec is not None:
                probe = R.retrieve(idx, qvec=qvec, texts=[digits_text], filters={"price": None, "attributes": []},
                                   intent="find_product", ctx=None, ent_products=ent_products, flags=fl)
                composite(idx, probe.candidates, has_dense=True, flags=fl)
            if probe and probe.candidates and probe.candidates[0]["final"] >= idx.thresholds["t_match"]:
                understanding["intent_llm"] = intent
                intent = understanding["intent"] = "find_product"
            else:
                if rr_task is not None:
                    rr_task.cancel()
                return self._finish(idx, request_id, "out_of_scope", None, [], understanding, [], False, fallback,
                                    lat, t_start, debug, [], top_k, filters)

        # embed câu viết lại (cờ thử nghiệm, tốn thêm 1 call tuần tự)
        if fl["embed_rewritten"] and rewritten and _jaccard(rewritten, text_norm) < 0.7:
            v2, err2, ms2 = await self._timed(self._embed(idx, norm_text(rewritten), persist))
            lat["embed"] += ms2
            if v2 is not None:
                qvec = v2 if qvec is None else (qvec + v2) / np.linalg.norm(qvec + v2)

        # Bước 2: truy xuất
        t0 = time.perf_counter()
        texts = [digits_text]
        if rewritten and _jaccard(rewritten, text_norm) < 0.7:
            texts.append(rewritten)
        rt = R.retrieve(idx, qvec=qvec, texts=texts, filters=filters, intent=intent, ctx=ctx,
                        ent_products=ent_products, flags=fl)
        cands = rt.candidates
        # Bước 3: điểm tổng hợp
        composite(idx, cands, has_dense=qvec is not None, flags=fl)
        lat["retrieve"] = (time.perf_counter() - t0) * 1000

        # Bước 4: gating + rerank
        exact_unique = ent.exact_unique if (ent and fl["entity"]) else None
        # hỏi chi tiết về đúng 1 sản phẩm lượt trước: sản phẩm đã rõ theo ngữ cảnh
        prev_ids = (ctx or {}).get("previous_product_ids") or []
        if (intent == "ask_detail" and len(prev_ids) == 1 and "previous" not in rt.relaxed_keys
                and any(c.key == "previous" for c in rt.constraints) and cands):
            cands[0]["score"] = max(cands[0]["score"], idx.thresholds["t_match"])
            exact_unique = cands[0]["product_id"]
        do_rr, _why = need_rerank(idx, cands, mode, exact_unique, fl)
        reranked = False
        if rr_task is not None:
            # rerank đã chạy song song với hiểu câu: chỉ chờ trong phần ngân sách còn lại; hết giờ thì dùng
            # thứ tự composite (bảo đảm không vượt deadline).
            if rr_task.done():
                results, err, lat["rerank"] = rr_task.result()
            else:
                wait = budget_s(10.0)
                if wait is not None and wait <= 0:
                    results, err = None, "deadline"
                else:
                    done, _ = await asyncio.wait({rr_task}, timeout=wait)
                    if done:
                        results, err, lat["rerank"] = rr_task.result()
                    else:
                        results, err = None, "deadline"
            if err == "deadline":
                rr_task.cancel()
                fallback.append("rerank_deadline")
            elif err:
                fallback.append(f"rerank_{err}")
            elif results and (do_rr or exact_unique is None):
                apply_rerank(idx, cands, results)
                reranked = True
        elif do_rr and (budget_s() is None or budget_s() > self.s.rerank_min_budget_ms / 1000):
            task = asyncio.create_task(self._timed(self._rerank(idx, rewritten or text, rt.constraints, cands, persist)))
            wait = budget_s(10.0)
            done = True
            if wait is not None:
                finished, _ = await asyncio.wait({task}, timeout=wait)
                done = bool(finished)
            if done:
                results, err, lat["rerank"] = await task
                if err:
                    fallback.append(f"rerank_{err}")
                elif results:
                    apply_rerank(idx, cands, results)
                    reranked = True
            else:
                task.cancel()
                fallback.append("rerank_deadline")
        elif do_rr:
            fallback.append("rerank_deadline")

        # Bước 5: quyết định
        status, close = decide(idx, cands, exact_unique)
        clarify = clarify_question(idx, close) if status == "ambiguous" else None
        return self._finish(idx, request_id, status, clarify, cands, understanding, rt.relaxed_keys, reranked,
                            fallback, lat, t_start, debug, rt.constraints, top_k, filters)

    def _finish(self, idx, request_id, status, clarify, cands, understanding, relaxed, reranked, fallback, lat,
                t_start, debug, constraints, top_k, filters):
        th = idx.thresholds
        products = []
        for rank, c in enumerate([c for c in cands if c["score"] >= th["t_min"]][:top_k], start=1):
            p = idx.products[c["i"]]
            products.append({
                "rank": rank, "product_id": p["id"], "sku": p["sku"], "name": p["name"], "price": p.get("price"),
                "price_unit": p.get("price_unit"), "in_stock": bool(p.get("in_stock", True)),
                "score": round(float(c["score"]), 4), "confidence": confidence(c["score"], th),
                "reason": c.get("reason") or template_reason(idx, c, constraints),
                "attributes": idx.attrs[c["i"]],
                "data": {k: v for k, v in p.items() if k not in DATA_HIDE},
            })
        lat_out = {k: round(v, 1) for k, v in lat.items()}
        lat_out["total"] = round((time.perf_counter() - t_start) * 1000, 1)
        resp = {
            "request_id": request_id, "status": status, "clarify_question": clarify, "products": products,
            "understanding": understanding, "relaxed": bool(relaxed), "relaxed_keys": relaxed,
            "reranked": reranked, "cache_hit": False, "fallback_reason": ",".join(fallback) or None,
            "latency_ms": lat_out, "data_version": idx.version,
        }
        top10 = [{
            "product_id": c["product_id"], "name": idx.products[c["i"]]["name"],
            "dense": {**c["dense_kinds"], "max_weighted_int8": _r(c["dense"]), "cos_f32": _r(c["cos"])},
            "bm25": _r(c["bm25"]), "entity": _r(c["entity"]), "soft": _r(c["soft"]), "rrf": _r(c["rrf"]),
            "stock": c["stock"], "prev": c["prev"], "cos_n": _r(c.get("cos_n")),
            "raw": _r(c.get("raw")), "final": _r(c.get("final")), "rerank": _r(c.get("rerank")), "rerank_sat": c.get("rerank_sat"), "score": _r(c["score"]),
        } for c in cands[:10]]
        if debug:
            resp["debug"] = {"candidates": top10, "constraints": [
                {"key": c.key, "desc": c.desc, "explicit": c.explicit, "weight": c.weight} for c in constraints],
                "thresholds": th}
        return resp, {"candidates": top10}

    def _log(self, idx, request_id, text, ctx, resp, extra) -> None:
        if self.log_sink is None:
            return
        self.log_sink({
            "demo_id": idx.demo_id, "request_id": request_id, "text": text, "context": ctx,
            "understanding": resp.get("understanding"), "candidates": (extra or {}).get("candidates"),
            "status": resp["status"], "product_ids": [p["product_id"] for p in resp["products"]],
            "reranked": resp["reranked"], "cache_hit": resp["cache_hit"], "fallback_reason": resp["fallback_reason"],
            "latency": resp["latency_ms"], "data_version": idx.version,
        })


def _r(x):
    return None if x is None else round(float(x), 4)
