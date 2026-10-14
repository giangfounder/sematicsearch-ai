"""Prompt + response_json_schema gửi Gemini. Phần tĩnh theo demo đặt trong system_instruction
(đứng trước, ổn định) để tận dụng implicit caching; phần động nằm trong contents."""
from __future__ import annotations

from app.catalog.texts import fmt_price

INTENTS = ["find_product", "ask_detail", "compare", "refine_previous", "out_of_scope", "chitchat"]
OPS = ["eq", "gte", "lte", "between", "approx"]


def _def_line(d: dict) -> str:
    vals = ""
    if d["type"] in ("enum", "multi_enum"):
        items = []
        for ev in d.get("enum_values") or []:
            v = ev["value"] if isinstance(ev, dict) else ev
            als = ev.get("aliases") if isinstance(ev, dict) else None
            items.append(f"{v}" + (f" (= {', '.join(als)})" if als else ""))
        vals = " | giá trị: " + "; ".join(items)
    alias = f" (còn gọi: {', '.join(d.get('label_aliases') or [])})" if d.get("label_aliases") else ""
    unit = f" | đơn vị: {d['unit']}" + (f" (= {', '.join(d.get('unit_aliases') or [])})" if d.get("unit_aliases") else "") if d.get("unit") else ""
    filt = " | lọc được" if d.get("filterable") else ""
    return f"- {d['key']}: {d['label']}{alias} | kiểu {d['type']}{unit}{vals}{filt}"


def understand_system(demo: dict, defs: list[dict], categories: list[str], brands: list[str],
                      price_unit: str | None, price_range: tuple[float, float] | None,
                      sample_names: list[str] | None = None) -> str:
    pr = ""
    if price_range:
        pr = f"- Khoảng giá trong danh mục: {fmt_price(price_range[0], price_unit)} – {fmt_price(price_range[1], price_unit)}\n"
    return (
        f'Bạn là bộ phân tích câu hỏi mua hàng cho "{demo["name"]}" (ngành: {demo.get("industry") or "bán lẻ"}).\n'
        "Câu khách là bản ghi giọng nói tự động: có thể sai chính tả, sai thanh, thiếu dấu, "
        "đọc tên nước ngoài kiểu Việt (ai phôn = iPhone, sam sung = Samsung), có từ đệm.\n"
        "Nhiệm vụ: hiểu khách muốn gì, sửa lỗi nghe nhầm DỰA TRÊN danh mục thật bên dưới, trích bộ lọc.\n\n"
        "Quy tắc:\n"
        "- Chỉ dùng category, hãng, key thuộc tính, giá trị enum có trong danh mục. Không bịa.\n"
        "- explicit=true chỉ khi khách nói rõ ràng buộc (\"dưới 10 triệu\", \"loại 2 cửa\", \"của Samsung\"). "
        "Mong muốn mơ hồ (\"tiết kiệm điện\", \"rộng rãi\", \"rẻ rẻ\") thì explicit=false.\n"
        "- Giá trả về bằng ĐỒNG (VND) đầy đủ. \"củ\" = triệu, \"k\" = nghìn, \"tỷ/tỉ\" = tỷ. "
        "\"tầm/khoảng/cỡ X\" dùng price.approx. \"rẻ nhất\" -> sort=asc, \"đắt nhất/cao cấp nhất\" -> sort=desc.\n"
        "- Thuộc tính số: value_num (between thì thêm value_num_max). Thuộc tính enum/bool/text: value_text "
        "(bool dùng \"true\"/\"false\").\n"
        "- Câu tiếp nối lượt trước (\"màu đen thì sao\", \"cái rẻ hơn\", \"loại kia\") -> ghép ngữ cảnh vào "
        "rewritten_query thành câu đầy đủ; intent=refine_previous (đổi điều kiện) hoặc ask_detail (hỏi thêm về sản phẩm đã nói).\n"
        "- compare: khách so sánh 2+ sản phẩm. out_of_scope: không liên quan sản phẩm/dịch vụ của cửa hàng. "
        "chitchat: chào hỏi, cảm ơn, hỏi ngoài lề. Câu hỏi theo nhu cầu, đối tượng, nơi chốn, hoàn cảnh sử dụng "
        "mà một mục trong danh mục có thể đáp ứng thì KHÔNG phải out_of_scope.\n"
        "- rewritten_query: câu tiếng Việt có dấu, rõ nghĩa, đã sửa lỗi ASR, giữ nguyên ý khách, không thêm điều kiện mới.\n"
        "- mentioned_products: tên/mã sản phẩm cụ thể khách nhắc tới, viết đúng như trong danh mục nếu nhận ra.\n\n"
        "Danh mục:\n"
        f"- Category: {'; '.join(categories) or '(không có)'}\n"
        f"- Hãng: {'; '.join(brands) or '(không có)'}\n"
        f"{pr}"
        + (f"- Các mục đang bán ({len(sample_names)} mục đầu): {'; '.join(sample_names)}\n" if sample_names else "")
        + "- Thuộc tính:\n" + "\n".join(_def_line(d) for d in defs)
    )


def understand_contents(text: str, ctx: dict | None, prev_names: list[str], candidate_names: list[str]) -> str:
    lines = []
    if ctx and (ctx.get("previous_text") or prev_names or ctx.get("previous_filters")):
        lines.append(f'Lượt trước: "{ctx.get("previous_text") or ""}"'
                     + (f" (sản phẩm đã nói: {'; '.join(prev_names)})" if prev_names else "")
                     + (f" (bộ lọc lượt trước: {ctx.get('previous_filters')})" if ctx.get("previous_filters") else ""))
    if candidate_names:
        lines.append("Sản phẩm có tên gần giống trong câu: " + "; ".join(candidate_names))
    lines.append(f'Câu khách: "{text}"')
    return "\n".join(lines)


def understand_schema(defs: list[dict], categories: list[str], brands: list[str]) -> dict:
    def nullable_enum(values: list[str]) -> dict:
        if not values or len(values) > 200:
            return {"type": ["string", "null"]}
        return {"type": ["string", "null"], "enum": [*values, None]}

    keys = [d["key"] for d in defs]
    attr_item = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "enum": keys} if keys else {"type": "string"},
            "op": {"type": "string", "enum": OPS},
            "value_num": {"type": ["number", "null"]},
            "value_num_max": {"type": ["number", "null"]},
            "value_text": {"type": ["string", "null"]},
            "unit": {"type": ["string", "null"]},
            "explicit": {"type": "boolean"},
        },
        "required": ["key", "op", "explicit"],
    }
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": INTENTS},
            "rewritten_query": {"type": "string"},
            "mentioned_products": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "filters": {
                "type": "object",
                "properties": {
                    "price": {
                        "type": ["object", "null"],
                        "properties": {
                            "min": {"type": ["number", "null"]},
                            "max": {"type": ["number", "null"]},
                            "approx": {"type": ["number", "null"]},
                            "sort": {"type": ["string", "null"], "enum": ["asc", "desc", None]},
                            "explicit": {"type": "boolean"},
                        },
                    },
                    "category": nullable_enum(categories),
                    "brand": nullable_enum(brands),
                    "in_stock": {"type": ["boolean", "null"]},
                    "attributes": {"type": "array", "maxItems": 8, "items": attr_item},
                },
                "required": ["attributes"],
            },
        },
        "required": ["intent", "rewritten_query", "mentioned_products", "filters"],
    }


RERANK_SYSTEM = (
    "Bạn chấm mức phù hợp giữa yêu cầu của khách và các sản phẩm ứng viên của cửa hàng.\n"
    "- relevance: 0 = không liên quan, 0.5 = liên quan một phần, 1 = đúng thứ khách cần.\n"
    "- satisfies_constraints: sản phẩm có thoả mọi ràng buộc \"nói rõ\" của khách không.\n"
    "- reason: CHỈ viết cho ĐÚNG MỘT sản phẩm phù hợp nhất: một cụm tiếng Việt rất ngắn (tối đa 12 từ) nêu điểm "
    "khớp chính (hãng/giá/thuộc tính), ví dụ \"Samsung, tiết kiệm điện, giá 9,8tr\". TẤT CẢ sản phẩm còn lại "
    "để reason là chuỗi rỗng. Viết càng ngắn càng tốt.\n"
    "Chấm tất cả sản phẩm được gửi, chỉ dùng đúng product_id trong danh sách."
)


def rerank_contents(query: str, constraints: list[str], lines: list[tuple[int, str]]) -> str:
    c = "; ".join(constraints) if constraints else "(không có)"
    body = "\n".join(f"[{pid}] {line}" for pid, line in lines)
    return f'Khách hỏi: "{query}"\nRàng buộc: {c}\nSản phẩm ứng viên:\n{body}'


def rerank_schema(ids: list[int]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array", "minItems": 1, "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer", "enum": ids},
                        "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                        "satisfies_constraints": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["product_id", "relevance", "satisfies_constraints", "reason"],
                },
            }
        },
        "required": ["results"],
    }
