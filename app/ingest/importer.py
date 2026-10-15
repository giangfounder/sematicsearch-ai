"""Import csv/xlsx/xls/json/jsonl: map cột lõi, cột còn lại -> thuộc tính dynamic (tự suy type/unit),
dry_run trả schema đề xuất + preview + cảnh báo; apply ghi DB trong 1 transaction."""
from __future__ import annotations

import io
import asyncio
import json
import math
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from app import repo
from app.db import bump_version
from app.schemas import AttributeDef
from app.text.normalize import norm_text, strip_accents

CORE_ALIASES: dict[str, list[str]] = {
    "sku": ["sku", "ma", "ma sp", "ma san pham", "code", "product code", "id"],
    "name": ["name", "ten", "ten san pham", "ten sp", "product", "product name", "san pham", "ten goi"],
    "category": ["category", "danh muc", "loai", "nhom", "nganh hang", "loai san pham"],
    "brand": ["brand", "hang", "thuong hieu", "nha san xuat", "hang san xuat"],
    "price": ["price", "gia", "gia ban", "don gia", "gia niem yet", "gia (vnd)"],
    "price_unit": ["price unit", "price_unit", "don vi gia", "dvt gia"],
    "in_stock": ["in stock", "in_stock", "con hang", "ton kho", "tinh trang", "stock"],
    "short_description": ["short description", "short_description", "mo ta ngan", "tom tat"],
    "description": ["description", "mo ta", "mo ta chi tiet", "chi tiet"],
    "aliases": ["aliases", "alias", "ten khac", "ten goi khac", "tu khoa", "keywords"],
    "use_cases": ["use cases", "use_cases", "cong dung", "phu hop", "danh cho"],
    "sample_questions": ["sample questions", "sample_questions", "cau hoi mau", "cau hoi"],
}
LIST_FIELDS = {"aliases", "use_cases", "sample_questions"}
TRUE_WORDS = {"co", "yes", "true", "1", "x", "con", "con hang", "c", "y", "dung"}
FALSE_WORDS = {"khong", "no", "false", "0", "het", "het hang", "k", "n", "sai"}
_UNIT_IN_HEADER = re.compile(r"^(.*?)\s*[\(\[]\s*([^\)\]]+?)\s*[\)\]]\s*$")
_NUM_UNIT = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*([^\d\s].{0,15})?\s*$")
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLUMNS = 256
_PARSE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="catalog-import")


def _k(s: str) -> str:
    return strip_accents(norm_text(str(s))).strip()


def slug_key(label: str) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", _k(label)).strip("_")
    return k or "attr"


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    if not data:
        raise ValueError("file trống")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file vượt quá giới hạn 20 MB")
    try:
        return _read_table(data, filename)
    except (BadZipFile, KeyError, TypeError, OSError, ParseError, InvalidFileException) as exc:
        raise ValueError("file hỏng hoặc không đúng định dạng đã chọn") from exc


def _read_table(data: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        with ZipFile(io.BytesIO(data)) as archive:
            if sum(f.file_size for f in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("file Excel sau giải nén vượt quá 100 MB")
        df = pd.read_excel(io.BytesIO(data), sheet_name=0, dtype=object, engine="openpyxl", nrows=MAX_ROWS + 1)
    elif name.endswith(".xls"):
        import xlrd

        try:
            df = pd.read_excel(io.BytesIO(data), sheet_name=0, dtype=object, engine="xlrd", nrows=MAX_ROWS + 1)
        except xlrd.XLRDError as exc:
            raise ValueError("file XLS hỏng hoặc không đúng định dạng") from exc
    elif name.endswith(".jsonl"):
        df = pd.DataFrame([json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()])
    elif name.endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig"))
        df = pd.DataFrame(obj["products"] if isinstance(obj, dict) and "products" in obj else obj)
    elif name.endswith((".csv", ".tsv")):
        text = data.decode("utf-8-sig", errors="replace")
        sep = "\t" if name.endswith(".tsv") else (";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ",")
        df = pd.read_csv(io.StringIO(text), dtype=object, sep=sep, keep_default_na=False, nrows=MAX_ROWS + 1)
    else:
        raise ValueError("chỉ hỗ trợ XLSX, XLSM, XLS, CSV, TSV, JSON, JSONL")
    df.columns = [unicodedata.normalize("NFC", str(c)).strip() for c in df.columns]
    df = df.dropna(how="all")
    if len(df) > MAX_ROWS or len(df.columns) > MAX_COLUMNS:
        raise ValueError("file vượt quá giới hạn 10.000 dòng hoặc 256 cột")
    if len(set(df.columns)) != len(df.columns):
        raise ValueError("tên cột bị trùng sau khi chuẩn hóa; hãy đổi tên cột")
    return df


def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and not math.isfinite(v):
        return True
    if v is pd.NA or v is pd.NaT:
        return True
    return isinstance(v, str) and not v.strip()


def parse_price(v) -> float | None:
    """'9.890.000' | '9,8tr' | '10 triệu' | '1,2 tỷ' | 9890000 -> float VND."""
    if _empty(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _k(v).replace("vnd", "").replace("dong", "").replace("d", "").strip()
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(ty|trieu|tr|cu|nghin|ngan|k)?\s*(\d+)?$", s)
    if m and m.group(2):
        mult = {"ty": 1e9, "trieu": 1e6, "tr": 1e6, "cu": 1e6, "nghin": 1e3, "ngan": 1e3, "k": 1e3}[m.group(2)]
        val = float(m.group(1).replace(",", ".")) * mult
        if m.group(3):
            val += float(m.group(3)) / (10 ** len(m.group(3))) * mult
        return val
    digits = re.sub(r"[.,\s]", "", s)
    if digits.isdigit():
        return float(digits)
    try:
        value = float(s.replace(",", "."))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if _empty(v):
        return None
    k = _k(v)
    if k in TRUE_WORDS:
        return True
    if k in FALSE_WORDS:
        return False
    try:
        return float(k) > 0
    except ValueError:
        return None


def split_list(v) -> list[str]:
    if _empty(v):
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[|\n;]", str(v)) if x.strip()]


def auto_mapping(columns: list[str]) -> dict[str, str]:
    """core field -> tên cột."""
    out: dict[str, str] = {}
    keys = {}
    for col in columns:
        m = _UNIT_IN_HEADER.match(col)
        keys[col] = _k(m.group(1) if m else col)  # "Giá (đồng/tháng)" -> "gia"
    for col, k in keys.items():
        for field, als in CORE_ALIASES.items():
            if field not in out and (k in als or k == field):
                out[field] = col
                break
    # tiền tố: "Mã gói", "Mã căn" -> mã dòng; "Tên gói", "Tên dự án" -> tên
    for field, prefixes in (("sku", ("ma ", "code ")), ("name", ("ten ",))):
        if field not in out:
            for col, k in keys.items():
                if col not in out.values() and k.startswith(prefixes):
                    out[field] = col
                    break
    return out


def infer_definitions(df: pd.DataFrame, attr_cols: list[str], existing: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    existing_by_label = {_k(d["label"]): d for d in existing or []}
    existing_by_key = {d["key"]: d for d in existing or []}
    defs, warns = [], []
    used = set()
    for order, col in enumerate(attr_cols):
        m = _UNIT_IN_HEADER.match(col)
        label, unit = (m.group(1).strip(), m.group(2).strip()) if m else (col, None)
        key = slug_key(label)
        while key in used:
            key += "_2"
        used.add(key)
        prev = existing_by_key.get(key) or existing_by_label.get(_k(label))
        if prev:
            d = {k: prev[k] for k in ("key", "label", "type", "unit", "unit_aliases", "label_aliases", "enum_values",
                                      "filterable", "searchable", "weight", "display_order")}
            d["_column"] = col
            defs.append(d)
            continue
        vals = [v for v in df[col].tolist() if not _empty(v)]
        n = len(vals)
        t, units_seen = "text", set()
        if n == 0:
            warns.append(f"Cột '{col}' trống hoàn toàn")
        else:
            nums = 0
            for v in vals:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums += 1
                    continue
                mm = _NUM_UNIT.match(str(v))
                if mm:
                    nums += 1
                    if mm.group(2):
                        units_seen.add(mm.group(2).strip())
            bools = sum(parse_bool(v) is not None and not str(v).strip().replace(".", "").isdigit() for v in vals)
            distinct = {norm_text(str(v)) for v in vals}
            has_multi = sum(bool(re.search(r"[,;|]", str(v))) for v in vals) >= 0.3 * n
            if nums >= 0.75 * n:
                t = "number"
                if not unit and len(units_seen) == 1:
                    unit = units_seen.pop()
                elif len(units_seen) > 1:
                    warns.append(f"Cột '{col}': nhiều đơn vị khác nhau {sorted(units_seen)}")
            elif bools >= 0.9 * n and len(distinct) <= 4:
                t = "bool"
            elif has_multi and len(distinct) > 2:
                parts = {norm_text(x) for v in vals for x in re.split(r"[,;|]", str(v)) if x.strip()}
                t = "multi_enum" if len(parts) <= 40 else "text"
            elif len(distinct) <= max(12, int(0.3 * n)) and len(distinct) < n:
                t = "enum"
        enum_values = []
        if t in ("enum", "multi_enum"):
            seen = {}
            for v in vals:
                items = re.split(r"[,;|]", str(v)) if t == "multi_enum" else [str(v)]
                for x in items:
                    x = x.strip()
                    if x and _k(x) not in seen:
                        seen[_k(x)] = x
            enum_values = [{"value": v, "aliases": []} for v in seen.values()]
        defs.append({"key": key, "label": label, "type": t, "unit": unit, "unit_aliases": [], "label_aliases": [],
                     "enum_values": enum_values, "filterable": t in ("number", "enum", "multi_enum", "bool"),
                     "searchable": True, "weight": 0.5, "display_order": order, "_column": col})
    return defs, warns


def normalize_attr(d: dict, v, warns: list[str], sku: str):
    if _empty(v):
        return None
    t = d["type"]
    if t == "number":
        if isinstance(v, (int, float)):
            return float(v)
        mm = _NUM_UNIT.match(str(v))
        if not mm:
            warns.append(f"{sku}: '{d['label']}' không phải số: {v!r}")
            return None
        return float(mm.group(1).replace(",", "."))
    if t == "bool":
        b = parse_bool(v)
        if b is None:
            warns.append(f"{sku}: '{d['label']}' không phải có/không: {v!r}")
        return b
    if t in ("enum", "multi_enum"):
        items = [x.strip() for x in re.split(r"[,;|]", str(v))] if t == "multi_enum" else [str(v).strip()]
        out = []
        for x in items:
            canon = None
            for ev in d.get("enum_values") or []:
                val = ev["value"] if isinstance(ev, dict) else ev
                als = ev.get("aliases", []) if isinstance(ev, dict) else []
                if any(_k(y) == _k(x) for y in [val, *als]):
                    canon = val
                    break
            if canon is None:
                warns.append(f"{sku}: '{d['label']}' giá trị lạ {x!r}")
                canon = x
            out.append(canon)
        return out if t == "multi_enum" else out[0]
    return str(v).strip()


def build_rows(df: pd.DataFrame, mapping: dict[str, str], defs: list[dict]) -> tuple[list[dict], list[str]]:
    warns: list[str] = []
    rows: list[dict] = []
    seen_sku: set[str] = set()
    def_cols = {d["_column"]: d for d in defs if d.get("_column")}
    used_cols = set(mapping.values()) | set(def_cols)
    for n, rec in enumerate(df.to_dict(orient="records"), start=2):
        get = lambda f: rec.get(mapping[f]) if f in mapping else None  # noqa: E731
        name = get("name")
        if _empty(name):
            warns.append(f"Dòng {n}: thiếu tên, bỏ qua")
            continue
        sku = get("sku")
        if _empty(sku):
            # không có cột mã: sinh khoá từ tên, thêm hậu tố nếu trùng (gửi lại cùng tên = cập nhật cùng dòng)
            base = slug_key(str(name))[:40]
            sku, k = base, 2
            while sku in seen_sku:
                sku, k = f"{base}-{k}", k + 1
        else:
            sku = str(int(sku)) if isinstance(sku, float) and float(sku).is_integer() else str(sku).strip()
            if sku in seen_sku:
                warns.append(f"Dòng {n}: trùng SKU {sku}, bỏ qua")
                continue
        seen_sku.add(sku)
        price_raw = get("price")
        price = parse_price(price_raw)
        if price is None and not _empty(price_raw):
            warns.append(f"Dòng {n} ({sku}): giá không đọc được {price_raw!r}")
        stock = parse_bool(get("in_stock"))
        row = {
            "sku": sku, "name": str(name).strip(),
            "category": None if _empty(get("category")) else str(get("category")).strip(),
            "brand": None if _empty(get("brand")) else str(get("brand")).strip(),
            "price": price, "price_unit": None if _empty(get("price_unit")) else str(get("price_unit")).strip(),
            "in_stock": True if stock is None else stock,
            "short_description": None if _empty(get("short_description")) else str(get("short_description")).strip(),
            "description": None if _empty(get("description")) else str(get("description")).strip(),
            "aliases": split_list(get("aliases")), "use_cases": split_list(get("use_cases")),
            "sample_questions": split_list(get("sample_questions")),
            "attributes": {}, "extra": {}, "raw": json_safe_row(rec),
        }
        for col, d in def_cols.items():
            v = normalize_attr(d, rec.get(col), warns, sku)
            if v is not None:
                row["attributes"][d["key"]] = v
        for col, v in rec.items():
            if col not in used_cols and not _empty(v):
                row["extra"][col] = v if isinstance(v, (int, float, bool)) else str(v)
        if any(row[f] for f in LIST_FIELDS):
            row["enrichment_status"] = "reviewed"
        rows.append(row)
    return rows, warns


def json_safe(v):
    if _empty(v):
        return None
    if isinstance(v, (bool, str)):
        return v
    if isinstance(v, (int, float)) or hasattr(v, "item"):
        try:
            x = v.item() if hasattr(v, "item") else v
        except (ValueError, AttributeError):
            x = v
        if isinstance(x, float) and x.is_integer():
            return int(x)
        return x
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def json_safe_row(rec: dict) -> dict:
    return {str(k): json_safe(v) for k, v in rec.items()}


def rows_from_records(records: list[dict], cfg: dict, defs: list[dict]) -> tuple[list[dict], list[str]]:
    """Dòng gửi qua API (đúng tên cột như file import đầu tiên) -> sản phẩm, dùng cấu hình map cột đã lưu."""
    df = pd.DataFrame([{unicodedata.normalize("NFC", str(k)).strip(): v for k, v in r.items()} for r in records],
                      dtype=object)
    col_of = {key: col for col, key in (cfg.get("def_columns") or {}).items()}
    defs2 = [dict(d, _column=col_of.get(d["key"])) for d in defs]
    mapping = {k: v for k, v in (cfg.get("mapping") or {}).items() if v in df.columns}
    if "name" not in mapping:
        return [], [f"Thiếu cột tên '{(cfg.get('mapping') or {}).get('name')}' trong dữ liệu gửi lên"]
    return build_rows(df, mapping, defs2)


async def plan_import(pool, demo_id: int | None, data: bytes, filename: str, mapping: dict | None = None,
                      definitions: list[dict] | None = None, attr_columns: list[str] | None = None) -> dict:
    existing = await repo.list_defs(pool, demo_id) if demo_id else []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_PARSE_POOL, _plan_import, data, filename, mapping, definitions, attr_columns, existing)


def _plan_import(data, filename, mapping, definitions, attr_columns, existing):
    if mapping is not None and (not isinstance(mapping, dict)
            or any(k not in CORE_ALIASES or not isinstance(v, str) for k, v in mapping.items())):
        raise ValueError("mapping phải là object tên trường -> tên cột")
    if definitions is not None:
        if not isinstance(definitions, list) or any(not isinstance(d, dict) for d in definitions):
            raise ValueError("definitions phải là danh sách thuộc tính")
        definitions = [{**AttributeDef.model_validate(d).model_dump(), **({"_column": d["_column"]} if "_column" in d else {})}
                       for d in definitions]
        if len({d["key"] for d in definitions}) != len(definitions):
            raise ValueError("definitions có key trùng nhau")
    df = read_table(data, filename)
    cols = list(df.columns)
    mp = auto_mapping(cols)
    if mapping:
        missing = set(mapping.values()) - set(cols)
        if missing:
            raise ValueError("mapping tham chiếu cột không tồn tại: " + ", ".join(sorted(missing)))
        mp.update(mapping)
    warns: list[str] = []
    if "name" not in mp:
        warns.append("Không tìm thấy cột tên sản phẩm (name/tên). Truyền mapping={'name': '<cột>'}")
    attr_cols = attr_columns if attr_columns is not None else [c for c in cols if c not in mp.values()]
    if any(col not in cols for col in attr_cols):
        raise ValueError("thuộc tính tham chiếu cột không tồn tại")
    if definitions:
        defs = [dict(d) for d in definitions]
        for d in defs:
            d.setdefault("_column", next((c for c in attr_cols if slug_key(_UNIT_IN_HEADER.sub(r"\1", c)) == d["key"]
                                          or c == d.get("label")), None))
            if d.get("_column") is not None and d["_column"] not in cols:
                raise ValueError("thuộc tính tham chiếu cột không tồn tại")
    else:
        defs, w = infer_definitions(df, attr_cols, existing)
        warns += w
    rows, w2 = build_rows(df, mp, defs) if "name" in mp else ([], [])
    warns += w2
    return {"mapping": mp, "proposed_definitions": [{k: v for k, v in d.items()} for d in defs],
            "rows": rows, "warnings": warns, "n_rows": len(rows), "columns": cols}


async def apply_import(pool, demo_id: int, plan: dict, mode: str = "upsert", *, connection=None) -> dict:
    defs = [{k: v for k, v in d.items() if not k.startswith("_")} for d in plan["proposed_definitions"]]
    cfg = {"mapping": plan["mapping"],
           "def_columns": {d["_column"]: d["key"] for d in plan["proposed_definitions"] if d.get("_column")},
           "columns": plan.get("columns") or []}
    async def write(conn):
        await repo.lock_demo(conn, demo_id)
        # nhớ cách map cột để API thêm/cập nhật dòng dùng đúng định dạng file gốc
        await conn.execute("UPDATE demos SET settings = settings || jsonb_build_object('import', $2::jsonb) WHERE id=$1",
                           demo_id, cfg)
        await repo.upsert_defs(conn, demo_id, defs, replace=False)
        ids = await repo.upsert_products(conn, demo_id, plan["rows"], mode=mode)
        version = await bump_version(conn, demo_id)
        return ids, version
    if connection is not None:
        ids, version = await write(connection)
    else:
        async with pool.acquire() as conn, conn.transaction():
            ids, version = await write(conn)
    return {"products": len(ids), "definitions": len(defs), "data_version": version}
