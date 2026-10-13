# Product Semantic Search — Thiết kế chi tiết (Giai đoạn 1)

> Trạng thái: **CHỜ DUYỆT**. Chưa có dòng code nào. Mục 12 là các câu hỏi cần bạn chốt.

---

## 0. Kiểm chứng tài liệu Gemini (tra ngày 2026-10-13, không đoán)

| Hạng mục | Kết quả tra cứu | Ảnh hưởng tới thiết kế |
|---|---|---|
| `gemini-2.5-flash-lite` | Còn chạy "until further notice" nhưng **chỉ cho user đã từng dùng**; Google khuyên dự án mới dùng `gemini-3.5-flash-lite` | Giữ mặc định 2.5 như yêu cầu, nhưng script smoke test kiểm tra quyền truy cập ngay đầu GĐ2; nếu key không gọi được thì chuyển `gemini-3.5-flash-lite` |
| Thinking | 2.5-flash-lite: **tắt mặc định**. 3.5-flash-lite: **bật ở mức `minimal`**, không thấy mức "off" | Với 3.5 đặt `thinking_level="minimal"` và đo latency. Docs mới chỉ có ví dụ trên Interactions API, nên smoke test phải xác nhận `generate_content` + `ThinkingConfig` vẫn nhận tham số này |
| Structured output (SDK `google-genai`) | `response_mime_type="application/json"` + `response_json_schema` (JSON Schema chuẩn) hoặc `response_schema` (Pydantic). Hỗ trợ `enum` cho string/number/integer, nullable bằng `["string","null"]`, `minimum/maximum`, `minItems/maxItems`. Schema quá lớn/lồng sâu có thể bị từ chối. Docs khuyên **không lặp schema trong prompt** | Dùng `response_json_schema` sinh động theo từng demo (enum key thuộc tính, enum product_id khi rerank). Vẫn validate lại phía server |
| Embedding | `gemini-embedding-001`: hỗ trợ `task_type` (`RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`…), `output_dimensionality` 128–3072 (khuyên 768/1536/3072), **phải tự normalize khi khác 3072**, tối đa 2048 token/input. Có model mới `gemini-embedding-2` (không dùng `task_type`, thay bằng prefix `task: search result \| query: ...`, tự normalize, 8192 token) | Dùng 001 + 768 + tự L2-normalize như yêu cầu. Để `gemini-embedding-2` làm 1 dòng trong ablation (đổi model = re-embed toàn bộ, nên lưu `embed_model` theo demo) |
| Async | `client.aio.models.generate_content / embed_content`, đóng bằng `await aclient.aclose()` | 1 client dùng chung mỗi API key, tạo lúc startup, đóng ở lifespan |
| Timeout / retry | `types.HttpOptions(timeout=<ms>)`, `retry_options=types.HttpRetryOptions(attempts, initial_delay, max_delay, http_status_codes)`, override được theo từng call | Tắt retry của SDK (`attempts=1`) cho call online, tự xử lý xoay key khi 429 để kiểm soát latency; job offline dùng retry SDK |
| Rerank | Gemini **không có model rerank chuyên dụng** | `GEMINI_RERANK_MODEL` = 1 model LLM (mặc định giống LLM model) chấm listwise bằng structured output |

Nguồn: ai.google.dev/gemini-api/docs/{models, thinking, structured-output, embeddings}, googleapis.github.io/python-genai, docs.cloud.google.com/vertex-ai/generative-ai/docs/retry-strategy.

---

## 1. Kiến trúc tổng thể

```
                  ┌────────────────────── FastAPI (1 process, async) ──────────────────────┐
 Bot / UI ──HTTP──▶ /v1/demos/{slug}/search                                                │
                  │   normalize → cache? → entity link (RAM, ~ms)                          │
                  │        └─ gather( understand[Gemini LLM], embed[Gemini], timeout riêng)│
                  │   → retrieve (RAM: filter, dense int8, BM25, RRF, f32 rescore)          │
                  │   → score → gating → [rerank Gemini] → decide → response               │
                  │   → log_queue (ghi DB bất đồng bộ, batch)                               │
                  │                                                                        │
                  │ DemoIndex cache (RAM, per demo, atomic swap)  ◀── LISTEN demo_changed ──┐ │
                  │ Job runner (import / enrich / embed / eval)  ── ghi DB ── NOTIFY ───────┘ │
                  └───────────────────────────────┬────────────────────────────────────────┘
                                                  │ asyncpg pool
                                           PostgreSQL 16 (nguồn gốc)
```

- **Search nóng không đọc DB.** Mọi thứ cần cho search nằm trong `DemoIndex` (RAM).
- Quy mô: 60 sản phẩm × ~15 vector ≈ 1k vector/demo → vài MB RAM. Có thể chạy 2–4 worker sau này (mỗi worker tự LISTEN và nạp cache), GĐ đầu chạy **1 worker** cho đơn giản và để cache response dùng chung.
- Không còn torch/model local → image `python:3.11-slim` multi-arch chạy thẳng trên arm64, build nhanh.

---

## 2. Schema PostgreSQL

```sql
CREATE TABLE demos (
  id            serial PRIMARY KEY,
  slug          text UNIQUE NOT NULL,
  name          text NOT NULL,
  industry      text,
  data_version  bigint NOT NULL DEFAULT 1,
  embed_model   text NOT NULL DEFAULT 'gemini-embedding-001',
  embed_dim     int  NOT NULL DEFAULT 768,
  thresholds    jsonb NOT NULL DEFAULT '{}',   -- xem mục 6.4
  settings      jsonb NOT NULL DEFAULT '{}',   -- hệ số chấm điểm override theo demo, từ đệm bổ sung
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attribute_definitions (
  id             serial PRIMARY KEY,
  demo_id        int NOT NULL REFERENCES demos ON DELETE CASCADE,
  key            text NOT NULL,                      -- snake_case, [a-z0-9_]
  label          text NOT NULL,
  type           text NOT NULL CHECK (type IN ('text','number','enum','multi_enum','bool')),
  unit           text,
  unit_aliases   text[] NOT NULL DEFAULT '{}',
  label_aliases  text[] NOT NULL DEFAULT '{}',
  enum_values    jsonb NOT NULL DEFAULT '[]',        -- [{value, aliases[]}]
  filterable     bool NOT NULL DEFAULT false,
  searchable     bool NOT NULL DEFAULT true,
  weight         real NOT NULL DEFAULT 0.5 CHECK (weight BETWEEN 0 AND 1),
  display_order  int  NOT NULL DEFAULT 0,
  UNIQUE (demo_id, key)
);

CREATE TABLE products (
  id                 serial PRIMARY KEY,
  demo_id            int NOT NULL REFERENCES demos ON DELETE CASCADE,
  sku                text NOT NULL,
  name               text NOT NULL,
  category           text,
  brand              text,
  price              numeric,
  price_unit         text,                -- 'VND', 'VND/tháng', 'VND/m2'...
  in_stock           bool NOT NULL DEFAULT true,
  short_description  text,
  description        text,
  attributes         jsonb NOT NULL DEFAULT '{}',
  aliases            text[] NOT NULL DEFAULT '{}',
  use_cases          text[] NOT NULL DEFAULT '{}',
  sample_questions   text[] NOT NULL DEFAULT '{}',
  enrichment_status  text NOT NULL DEFAULT 'none' CHECK (enrichment_status IN ('none','ai_draft','reviewed')),
  extra              jsonb NOT NULL DEFAULT '{}', -- cột import không map được, trả trong "data"
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (demo_id, sku)
);

CREATE TABLE product_vectors (
  id           bigserial PRIMARY KEY,
  product_id   int NOT NULL REFERENCES products ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('name','profile','use_case','question')),
  source_text  text NOT NULL,
  text_hash    text NOT NULL,             -- sha1(embed_model|dim|task|source_text) → chỉ re-embed khi đổi
  embed_model  text NOT NULL,
  vec_int8     bytea NOT NULL,            -- 768 byte
  scale        real NOT NULL,             -- x ≈ int8 * scale
  vec_f32      bytea,                     -- 3 KB; lưu để khởi động không phải gọi lại API (xem rủi ro R7)
  UNIQUE (product_id, kind, text_hash)
);

CREATE TABLE eval_cases (
  id                    serial PRIMARY KEY,
  demo_id               int NOT NULL REFERENCES demos ON DELETE CASCADE,
  query                 text NOT NULL,
  context               jsonb,
  expected_product_ids  int[] NOT NULL DEFAULT '{}',
  expected_status       text NOT NULL,
  category              text,       -- name|alias|asr|no_accent|use_case|price|numeric_attr|multi_turn|ambiguous|out_of_scope|compare
  split                 text NOT NULL DEFAULT 'test' CHECK (split IN ('dev','test')),  -- THÊM: tránh calibrate & báo số trên cùng tập
  source                text NOT NULL CHECK (source IN ('manual','ai','log')),
  active                bool NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE search_logs (
  id            bigserial PRIMARY KEY,
  demo_id       int NOT NULL,
  request_id    text UNIQUE NOT NULL,
  text          text NOT NULL,
  context       jsonb,
  understanding jsonb,
  candidates    jsonb,               -- top 10 + điểm từng tín hiệu
  status        text,
  product_ids   int[],
  reranked      bool,
  cache_hit     bool,
  fallback_reason text,
  latency       jsonb,
  data_version  bigint,
  feedback      jsonb,               -- {correct, correct_product_id, at}
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON search_logs (demo_id, created_at DESC);

-- THÊM so với đề bài: job bền vững (bản cũ mất khi restart)
CREATE TABLE jobs (
  id          text PRIMARY KEY,
  demo_id     int,
  kind        text NOT NULL,   -- import|enrich|embed|gen_eval|evaluate|calibrate
  status      text NOT NULL,   -- queued|running|done|error|cancelled
  progress    real NOT NULL DEFAULT 0,
  params      jsonb, result jsonb, error text,
  created_at  timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

-- THÊM: đếm token/chi phí
CREATE TABLE gemini_usage (
  day date, demo_id int, call_type text, model text,
  calls int, input_tokens bigint, output_tokens bigint, errors int,
  PRIMARY KEY (day, demo_id, call_type, model)
);
```

**Đồng bộ data_version**: mọi API ghi (products, definitions, vectors) chạy trong 1 transaction và kết thúc bằng
`UPDATE demos SET data_version = data_version + 1 ... RETURNING` + `SELECT pg_notify('demo_changed', slug||':'||version)`.
Backend `LISTEN demo_changed` → build `DemoIndex` mới ở nền → gán tham chiếu (atomic swap). Thêm **poll 30s** so sánh `data_version` phòng khi kết nối LISTEN rớt. Cache response chứa `data_version` trong key nên tự vô hiệu.

Migration: file SQL đánh số `migrations/NNN_*.sql`, áp dụng lúc startup qua bảng `schema_migrations` (không dùng Alembic cho gọn).

---

## 3. Luồng offline

### 3.1 Import (`POST /v1/admin/demos/{slug}/import`, multipart, `dry_run=true` mặc định)
1. Đọc csv/xlsx (pandas + openpyxl), chuẩn hoá tên cột.
2. Map cột lõi theo tên/alias (`sku|mã`, `name|tên sản phẩm`, `giá|price`…) hoặc theo `mapping` bạn gửi kèm.
3. Cột còn lại → **đề xuất attribute_definitions**: suy `type` (≥90% parse được số → number; ≤12 giá trị phân biệt & lặp → enum; có dấu `,`/`;` tách nhiều giá trị → multi_enum; có/không, yes/no → bool; còn lại text), tách `unit` từ header hoặc hậu tố giá trị (`"300 lít"` → 300 + `lít`), đề xuất `filterable` cho number/enum/bool.
4. Parse giá kiểu Việt: `9.890.000`, `9,8tr`, `10 triệu`, `1,2 tỷ`.
5. `dry_run=true` → trả `{proposed_definitions, mapping, preview(10 dòng đã chuẩn hoá), warnings[]}` (trùng SKU, thiếu tên, giá không parse được, giá trị enum lạ). Không ghi DB.
6. `dry_run=false` + `definitions` bạn đã sửa → upsert theo `(demo_id, sku)`, mode `upsert|replace`. Tạo job `embed` cho vector đổi `text_hash`.

`GET /v1/admin/demos/{slug}/template.xlsx`: sheet `products` với cột lõi + 1 cột/thuộc tính (header `label (unit)`), sheet `definitions`, data validation cho enum.

### 3.2 Enrich (`POST /v1/admin/demos/{slug}/enrich`, job nền, `dry_run`)
- Gọi Gemini theo lô 5 sản phẩm/call, structured output: `{product_id, aliases[], use_cases[], sample_questions[]}`.
- Prompt yêu cầu rõ các loại alias: viết tắt, không dấu, tên ngoại đọc kiểu Việt ("ai phôn", "sam sung", "ô pô"), lỗi nghe nhầm thanh/âm cuối ("tủ lạnh" → "tủ lãnh"), cách nói số ("bốn mươi ba in" cho TV 43 inch).
- Chỉ điền trường đang rỗng, hoặc trường trong `overwrite_fields`. `enrichment_status='ai_draft'`.
- `dry_run=true` → lưu kết quả vào `jobs.result`, UI hiển thị diff để duyệt → `POST .../enrich/{job_id}/apply` với danh sách sản phẩm được chấp nhận (cho phép sửa tay) → `reviewed` nếu bạn đánh dấu.

### 3.3 Sinh vector
| kind | source_text |
|---|---|
| name | `"{name} – {brand}. Tên khác: {aliases…}"` |
| profile | `"{category}. {short_description}. {label}: {value} {unit}; …"` (chỉ thuộc tính `searchable`) |
| use_case | mỗi use_case 1 vector |
| question | mỗi sample_question 1 vector |

`task_type=RETRIEVAL_DOCUMENT`, `output_dimensionality=768`, gom lô 100 text/call, L2-normalize, lượng tử hoá **đối xứng theo từng vector**: `scale = max|x|/127`, `q = round(x/scale)`.

### 3.4 Sinh eval_cases (`POST .../eval/generate`, dry_run)
- Prompt **khác hẳn** prompt enrich, được cấm dùng lại `sample_questions`/aliases nguyên văn (đưa danh sách vào để né), yêu cầu phân bổ theo `category` (tên, alias, ASR, không dấu, công dụng, giá, thuộc tính số, nhiều lượt, mơ hồ, so sánh, ngoài phạm vi).
- Lọc rò rỉ: bỏ câu có chuẩn hoá trùng hoặc cosine ≥ 0.95 với bất kỳ `question` vector nào của demo.
- Câu mơ hồ được sinh bằng cách chọn **nhóm sản phẩm thật sự giống nhau** (cùng category, khác 1 thuộc tính) → `expected_status=ambiguous`, `expected_product_ids` = cả nhóm.
- Gán `split` ngẫu nhiên có phân tầng theo category: 40% dev / 60% test.
- Seed thêm câu `manual` do tôi viết tay (không qua LLM) để giảm thiên lệch "LLM tự sinh, LLM tự chấm".

### 3.5 Từ điển thực thể (build khi nạp `DemoIndex`)
Bề mặt (surface form) → `[(entity_type, target, strength)]`:
- product: name, aliases, sku (strength 1.0); tên rút gọn bỏ hãng/category (0.8)
- brand, category, enum value + aliases, unit aliases, label aliases
Mỗi bề mặt lưu 2 bản (có dấu, không dấu). Index: dict exact + index trigram ký tự (cho fuzzy).

---

## 4. Luồng online (`POST /v1/demos/{slug}/search`)

### Bước 0 — Chuẩn hoá & cache
`NFC → lower → bỏ dấu câu (giữ . , trong số "9,8") → bỏ từ đệm (danh sách mặc định + demos.settings.fillers) → gộp khoảng trắng`, tạo thêm `text_noacc`.
Số nói thành chữ được chuẩn hoá ở bước parser (không ở đây) để không phá cách viết khác.

Cache (cachetools, TTL):
| Lớp | Key | TTL |
|---|---|---|
| response | (demo, data_version, text_norm, ctx_hash, top_k, mode) | 10 phút |
| understanding | (demo, data_version, text_norm, ctx_hash) | 1 giờ |
| query embedding | (embed_model, dim, text_norm) | 24 giờ (không phụ thuộc version) |

`ctx_hash` = hash của `previous_text` đã chuẩn hoá + `previous_product_ids` + `previous_filters`. Có cache-stampede guard (1 future/key).

### Bước 1 — Hiểu câu
**(c) entity linking chạy TRƯỚC** (vài ms, đồng bộ) vì (a) cần top 20 tên ứng viên. Sau đó `asyncio.gather` (a) + (b):

- **(c) Entity linking**: sinh n-gram 1–5 âm tiết của `text_noacc`; tra exact; nếu không có thì fuzzy (trigram Jaccard ≥ 0.5 lọc thô → `rapidfuzz.ratio` ≥ 85). Tham lam theo độ dài, không chồng lấn. Output: `products[{id, score, match:'exact'|'fuzzy', surface}]`, `brands`, `categories`, `enum_hits`.
- **(a) Understand** (timeout 1200 ms): prompt ở mục 5.1.
- **(b) Embed** (timeout 800 ms): `text_norm`, `RETRIEVAL_QUERY`, 768, normalize.
- **Rule parser** (luôn chạy, ~1 ms): giá (`10 củ`, `10tr`, `mười triệu`, `chín triệu rưỡi`, `1 tỷ 2`, `dưới/trên/từ…đến/tầm/khoảng/rẻ nhất`), số + đơn vị theo `unit_aliases` (`2 cánh`/`2 cửa`, `300 lít`, `128 gb`, `70 mét vuông`), enum alias, brand/category từ (c).

Hợp nhất & validate:
- Bỏ attribute `key` lạ, sai kiểu, enum ngoài danh sách (thử map qua alias trước khi bỏ). `category/brand` phải thuộc catalog.
- Mâu thuẫn ở **giá / số** → rule thắng. Rule có mà LLM không có → thêm vào (explicit=true nếu có từ khoá rõ).
- `out_of_scope|chitchat` → trả ngay (nhưng nếu (c) có entity exact thì bỏ qua phán đoán OOS của LLM — chống LLM từ chối nhầm).
- Lỗi (a) → `fallback_reason="understand_timeout|understand_error"`, dùng rule + câu gốc. Lỗi (b) → `"embed_error"`, chỉ BM25 + entity.

### Bước 2 — Truy xuất trên RAM
1. **Lọc cứng**: chỉ ràng buộc `explicit=true` trên thuộc tính `filterable` (+ price, brand, category nói rõ). `approx` (tầm/khoảng) → dải ±20% (config) cứng + điểm mềm theo độ gần.
2. Rỗng → **nới dần**: bỏ ràng buộc có `weight` thấp nhất, lặp lại; ghi `relaxed_keys`. Ràng buộc đã nới chuyển thành điểm mềm.
3. **Dense**: `S = Q_int8 · V_int8ᵀ * (s_q * s_v)` trên mọi vector của sản phẩm còn lại → điểm sản phẩm = `max_kind( w_kind * cos )`, `w = {question:1.0, name:0.97, use_case:0.93, profile:0.90}` (config, chốt bằng ablation).
4. **BM25** (tự cài trên numpy, corpus nhỏ): token = âm tiết + bigram, index 2 bản có dấu & không dấu, 2 trường: `name+aliases+sku` (trọng số 1.0) và `profile` (0.6). Query không dấu khớp bản không dấu. Nếu `rewritten_query` khác câu gốc (Jaccard token < 0.7) → BM25 thêm lần nữa trên câu viết lại, lấy max. Cờ `EMBED_REWRITTEN=1` để thử embed câu viết lại (ablation).
5. **RRF**: `rrf(p) = Σ_s w_s / (k + rank_s(p))`, k=20 (corpus nhỏ, k=60 làm phẳng quá), `w = {dense:1.0, bm25:0.8, entity:1.5}`. Entity exact của sản phẩm được đặt rank 1 kênh entity.
6. Top 30 → **chấm lại cosine float32** (dot với vector f32, cũng lấy max theo kind).
7. Ngữ cảnh: `intent ∈ {refine_previous, ask_detail}` và có `previous_product_ids` → cộng điểm mềm cho các sản phẩm đó (`w_prev`), và nếu câu không nhắc entity mới thì giới hạn ứng viên trong nhóm đó + cùng category.

### Bước 3 — Điểm tổng hợp (`search/scoring.py`)
```
cos_n   = clip((cos_f32 - c_lo) / (c_hi - c_lo), 0, 1)   # c_lo, c_hi học từ phân phối cos của demo (p5 câu sai / p95 câu đúng)
rrf_n   = rrf / rrf_max_possible
ent     = điểm entity (exact 1.0, fuzzy = ratio/100, không khớp 0)
soft    = Σ weight_i * sat_i / Σ weight_i   (sat_i ∈ [0,1], ví dụ giá: 1 - |price - target| / band)
stock   = 1 nếu còn hàng, 0 nếu hết
raw     = a1*cos_n + a2*rrf_n + a3*ent + a4*soft + a5*stock + a6*prev
          mặc định a = (0.45, 0.20, 0.20, 0.10, 0.03, 0.02)
final   = sigmoid(A * raw + B)       # Platt scaling học trên eval_cases split=dev, lưu A,B vào demos.thresholds
```
`final` ≈ xác suất top-1 đúng → ngưỡng có nghĩa thống nhất giữa các demo. Trước khi calibrate: A=10, B=-5.

### Bước 4 — Gating rerank
- `mode=fast` → không bao giờ. `mode=accurate` → luôn. `mode=auto`:
  - **Bỏ qua** nếu entity exact khớp đúng 1 sản phẩm (và sản phẩm đó qua lọc cứng), **hoặc** `final1 ≥ gate_high` và `final1 - final2 ≥ gate_margin`.
  - Ngược lại rerank top 10 (timeout 2500 ms). Lỗi → giữ thứ tự bước 3, `fallback_reason="rerank_error"`.
- Điểm sau rerank: `score = (1-β)*final + β*relevance`, nếu `satisfies_constraints=false` thì `score *= 0.6`. β=0.6, calibrate.

### Bước 5 — Quyết định
```
s1, s2 = điểm top1, top2
matched      : s1 ≥ t_match  và  (s1 - s2 ≥ margin  hoặc  entity exact 1 sản phẩm)
ambiguous    : s1 ≥ t_min và không matched và có ≥2 ứng viên trong [s1 - margin_amb, s1]
no_match     : s1 < t_min
(1 ứng viên duy nhất ≥ t_min nhưng < t_match → xem câu hỏi Q3)
out_of_scope : từ bước 1
```
- `products`: tối đa `top_k` sản phẩm có `score ≥ t_min`, kể cả khi ambiguous.
- `confidence`: high ≥ t_match, medium ≥ t_min, low còn lại.
- **clarify_question**: trong tập sát điểm, tìm thuộc tính có giá trị khác nhau, ưu tiên `filterable` → `weight` cao → ít giá trị phân biệt (2–3 lựa chọn dễ hỏi qua thoại). Template theo type:
  - enum/bool/number: `"Anh/chị muốn loại {v1} hay {v2} ạ?"` (number kèm unit: "1 cửa hay 2 cửa")
  - không có thuộc tính phân biệt → theo tên: `"Anh/chị đang hỏi {name1} hay {name2} ạ?"`
  - template override được trong `demos.settings.clarify_templates`.
- `reason`: nếu có rerank thì dùng reason của Gemini; không thì ghép template từ thuộc tính khớp ràng buộc (`"Samsung, Inverter tiết kiệm điện, giá 9,8tr (khoảng 10tr)"`).

---

## 5. Prompt & response_schema gửi Gemini

### 5.1 Understand
`system_instruction` (phần TĨNH theo demo đặt trước để tận dụng implicit cache của Gemini — sẽ kiểm tra `cached_content_token_count` trong usage):
```
Bạn là bộ phân tích câu hỏi mua hàng cho cửa hàng "{demo.name}" ({industry}).
Câu khách là bản ghi giọng nói tự động, có thể sai chính tả, sai thanh, thiếu dấu, đọc tên nước ngoài kiểu Việt.
Nhiệm vụ: hiểu khách muốn gì, sửa lỗi nghe nhầm DỰA TRÊN danh mục thật bên dưới, trích bộ lọc.
Quy tắc:
- Chỉ dùng category, brand, key thuộc tính, giá trị enum có trong danh mục. Không bịa.
- explicit=true chỉ khi khách nói rõ ràng buộc ("dưới 10 triệu", "loại 2 cửa", "của Samsung").
  Mong muốn mơ hồ ("tiết kiệm điện", "rộng rãi", "rẻ rẻ") → explicit=false.
- "củ", "chai", "lít" (tiền) = triệu đồng. "tầm/khoảng X" → op=approx.
- Nếu câu là tiếp nối lượt trước ("màu đen thì sao", "cái rẻ hơn"), ghép ngữ cảnh vào rewritten_query
  và đặt intent=refine_previous hoặc ask_detail.
- out_of_scope: không liên quan sản phẩm của cửa hàng. chitchat: chào hỏi, cảm ơn, hỏi ngoài lề.
Danh mục:
- Category: {...}
- Hãng: {...}
- Thuộc tính: key | nhãn (tên gọi khác) | kiểu | đơn vị | giá trị cho phép
  {...}
```
`contents` (phần ĐỘNG):
```
Lượt trước: "{previous_text}" (sản phẩm đã nói: {tên các previous_product_ids}; bộ lọc: {previous_filters})
Sản phẩm có tên gần giống trong câu: {top 20 tên từ entity linking / BM25 tên}
Câu khách: "{text gốc}"
```
`response_json_schema` (sinh theo demo; `attr_keys`, `categories`, `brands` là enum động):
```json
{
  "type": "object",
  "properties": {
    "intent": {"type": "string", "enum": ["find_product","ask_detail","compare","refine_previous","out_of_scope","chitchat"]},
    "rewritten_query": {"type": "string"},
    "mentioned_products": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    "filters": {
      "type": "object",
      "properties": {
        "price": {"type": ["object","null"], "properties": {
            "min": {"type": ["number","null"]}, "max": {"type": ["number","null"]},
            "approx": {"type": ["number","null"]},
            "sort": {"type": ["string","null"], "enum": ["asc","desc",null]},
            "explicit": {"type": "boolean"}}},
        "category": {"type": ["string","null"], "enum": ["<categories>", null]},
        "brand": {"type": ["string","null"], "enum": ["<brands>", null]},
        "in_stock": {"type": ["boolean","null"]},
        "attributes": {"type": "array", "maxItems": 8, "items": {
          "type": "object",
          "properties": {
            "key": {"type": "string", "enum": ["<attr_keys>"]},
            "op": {"type": "string", "enum": ["eq","gte","lte","between","approx"]},
            "value_num": {"type": ["number","null"]},
            "value_num_max": {"type": ["number","null"]},
            "value_text": {"type": ["string","null"]},
            "unit": {"type": ["string","null"]},
            "explicit": {"type": "boolean"}},
          "required": ["key","op","explicit"]}}
      },
      "required": ["attributes"]
    }
  },
  "required": ["intent","rewritten_query","mentioned_products","filters"]
}
```
Giá trị đổi về VND ở backend (LLM trả "10" + "triệu" hay 10000000 đều chuẩn hoá được; prompt yêu cầu VND đầy đủ). Cấu hình: `temperature=0`, `max_output_tokens=400`, 2.5: không thinking; 3.5: `thinking_level=minimal`.

### 5.2 Rerank
```
Khách hỏi: "{rewritten_query}"
Ràng buộc: {filters dạng câu: "giá khoảng 10 triệu (nói rõ); hãng Samsung (nói rõ); tiết kiệm điện (mong muốn)"}
Sản phẩm ứng viên:
[{id}] {name} | {giá} | {3–6 thuộc tính chính} | Dùng cho: {use_cases[:3]}
...
Chấm mức phù hợp của từng sản phẩm với câu hỏi (0 = không liên quan, 1 = đúng thứ khách cần).
satisfies_constraints = sản phẩm có thoả các ràng buộc "nói rõ" không.
reason: 1 câu tiếng Việt ngắn, tự nhiên, để nhân viên đọc cho khách, nêu điểm khớp chính; không bịa thông tin ngoài dữ liệu.
```
```json
{"type":"object","properties":{"results":{"type":"array","minItems":1,"maxItems":10,"items":{
  "type":"object","properties":{
    "product_id":{"type":"integer","enum":[<10 id đã gửi>]},
    "relevance":{"type":"number","minimum":0,"maximum":1},
    "satisfies_constraints":{"type":"boolean"},
    "reason":{"type":"string"}},
  "required":["product_id","relevance","satisfies_constraints","reason"]}}},"required":["results"]}
```
Server vẫn lọc id ngoài danh sách, bỏ trùng, sản phẩm thiếu trong kết quả giữ điểm bước 3 với relevance = 0.3.

### 5.3 Enrich & sinh eval: viết trong GĐ2, cùng kiểu (structured output, schema có `product_id` enum).

---

## 6. Gemini client, cache, hiệu năng

- `GeminiPool`: 1 `genai.Client` / key (từ `GEMINI_API_KEY=k1,k2,k3`), round-robin; 429/RESOURCE_EXHAUSTED → key đó cooldown 30 s, thử key kế (tối đa 1 lần cho call online). Key không bao giờ được log (logger có filter che chuỗi `AIza…`).
- Timeout riêng: `UNDERSTAND_TIMEOUT_MS=1200`, `EMBED_TIMEOUT_MS=800`, `RERANK_TIMEOUT_MS=2500`, `OFFLINE_TIMEOUT_MS=60000` — vừa đặt ở `HttpOptions(timeout)` vừa bọc `asyncio.wait_for`.
- Rate limiter token-bucket theo call type; **circuit breaker** theo call type (5 lỗi liên tiếp → mở 20 s → half-open): khi mở thì đi thẳng fallback, không chờ timeout.
- Warm-up lúc startup: 1 embed + 1 generate nhỏ để mở kết nối TLS/HTTP2.
- `usage_metadata` → cộng dồn vào bộ đếm RAM → flush `gemini_usage` mỗi 30 s; `/health` hiển thị calls, token, lỗi, trạng thái breaker, latency p50/p95 gần nhất theo call type.
- Log search: `asyncio.Queue` → writer gom 50 bản ghi hoặc 1 s → `executemany`.

**Ngân sách latency dự kiến** (chưa đo, Oracle → Google):
| Bước | Dự kiến |
|---|---|
| normalize + entity + rule | < 5 ms |
| gather(understand, embed) | ≈ max(400–700, 150–300) ms |
| retrieve + score | < 10 ms |
| rerank (khi gating gọi) | + 500–900 ms |
| cache hit | < 5 ms |

---

## 7. API

Search: `POST /v1/demos/{slug}/search` — đúng hợp đồng trong đề bài; `debug=true` thêm `debug.candidates[10]` với `{product_id, dense:{name,profile,use_case,question}, dense_max, cos_f32, bm25, bm25_rewritten, entity, soft, rrf, raw, final, rerank, filtered_out_by}`.
Feedback: `POST /v1/search/{request_id}/feedback` `{correct, correct_product_id?, add_to_eval?: bool}`.

Quản trị (prefix `/v1/admin`, header `X-Admin-Key`):
- `GET/POST/PATCH/DELETE /demos`, `/demos/{slug}/definitions`, `/demos/{slug}/products[/{id}]`
- `POST /demos/{slug}/import?dry_run=` · `GET /demos/{slug}/template.xlsx`
- `POST /demos/{slug}/enrich?dry_run=` · `POST /demos/{slug}/enrich/{job_id}/apply`
- `POST /demos/{slug}/eval/generate?dry_run=` · CRUD `/demos/{slug}/eval_cases`
- `GET /jobs/{id}` · `GET /jobs?demo=`
- `POST /v1/demos/{slug}/evaluate` (job) · `POST /v1/demos/{slug}/calibrate` (job)
- `GET /health` (công khai bản rút gọn; bản đầy đủ cần admin key)

Auth search: `X-API-Key` (env `API_KEYS`), để trống = mở (chỉ cho dev).

---

## 8. Đánh giá & calibrate

`evaluate` (tham số `split=test|dev|all`, `mode`, `concurrency=4`, `no_cache=true`):
- `hit@1`, `hit@3`, `MRR` — chỉ trên case có `expected_product_ids` không rỗng.
- Ma trận nhầm lẫn status, độ chính xác status.
- **matched_wrong_rate** = (#status=matched và top1 ∉ expected) / (#status=matched). Báo kèm **khoảng tin cậy Wilson 95%** vì n nhỏ.
- Tỷ lệ gọi rerank, fallback; latency p50/p95 theo bước (lấy từ response, cache tắt).
- Bảng theo `category` của case (tên/alias/ASR/giá…), danh sách câu sai + debug.
- Gợi ý: sản phẩm bị trả sai ≥2 lần → đề xuất thêm alias/sample_question, kèm câu sai làm nguyên liệu.

`calibrate` (chỉ trên `split=dev`): 
1. Fit Platt `A, B` (logistic 1 biến trên `raw` → đúng/sai top1).
2. Grid search `t_match, t_min, margin, gate_high, gate_margin, β` tối đa hoá `hit-đúng-matched` với ràng buộc `matched_wrong_rate ≤ 2%` (cận trên Wilson) và tỷ lệ rerank tối thiểu.
3. Lưu vào `demos.thresholds` (+ lịch sử trong `jobs.result`), tăng `data_version`. Sau đó evaluate trên `test` để báo số không bị "học tủ".

`scripts/ablation.py --demo dienmay`: chạy evaluate với các cờ `ABL_*` (multi_vector, bm25, entity, soft_filter, float_rescore, rerank, embed_rewritten, embedding-2) → bảng markdown hit@1/hit@3/matched_wrong/p95.

---

## 9. Kế hoạch triển khai theo giai đoạn

**GĐ2** (thước đo trước): docker-compose (postgres + app), migrations, config, GeminiPool + smoke script, import + dry_run + template, enrich, vector, DemoIndex + LISTEN/NOTIFY, cache, seed 3 demo, sinh + review eval_cases, endpoint evaluate (chạy được với pipeline "rỗng"), UI khung. Test pytest mock Gemini.

**GĐ3** — mỗi bước 1 dòng trong bảng so sánh (đo trên `split=test` mỗi demo):
| # | Cấu hình |
|---|---|
| B0 | Baseline giống bản cũ: LLM tách lọc → lọc cứng → cosine int8 1 vector/sản phẩm (profile) → top 1 |
| B1 | + đa vector (name/profile/use_case/question, max theo kind) |
| B2 | + BM25 có dấu/không dấu + RRF |
| B3 | + entity linking (+ đưa ứng viên vào prompt understand) |
| B4 | + lọc cứng chỉ explicit, ràng buộc mềm, nới điều kiện |
| B5 | + rescore float32 + hàm điểm tổng hợp |
| B6 | + ngữ cảnh nhiều lượt |
| B7 | + rerank (gating auto) — so cả fast / auto / accurate |

**GĐ4**: calibrate theo demo, tối ưu latency (đo trước/sau), README (giải thích hệ số), Dockerfile arm64, hướng dẫn deploy Oracle.

---

## 10. Danh sách file

```
.env.example  .gitignore  .dockerignore  Dockerfile  docker-compose.yml  requirements.txt  README.md
docs/DESIGN.md
migrations/001_init.sql
app/
  main.py                 # FastAPI, lifespan (pool, migrate, gemini warm-up, load index, LISTEN, log writer)
  config.py               # pydantic-settings, mọi hệ số/ngưỡng mặc định
  db.py                   # asyncpg pool, migrator, notify listener + poll
  security.py             # API key / admin key, filter che key trong log
  api/ search.py  admin.py  eval.py  ui.py
  schemas/ api.py  llm.py # pydantic request/response; schema JSON gửi Gemini (sinh động)
  gemini/ pool.py  breaker.py  usage.py  prompts.py
  text/ normalize.py  vn_numbers.py  tokenize.py
  catalog/ index.py  quant.py  bm25.py  entity.py  loader.py
  search/ pipeline.py  understand.py  rules.py  filters.py  retrieve.py  fusion.py
          scoring.py  rerank.py  decide.py  clarify.py  cache.py  context.py
  ingest/ importer.py  infer_schema.py  template_xlsx.py  enrich.py  vectors.py
  evals/ generate.py  evaluate.py  calibrate.py  metrics.py
  jobs.py  logs.py
  static/index.html       # UI test (HTML + JS thuần, không build)
seeds/ dienmay/  vienthong/  batdongsan/   # products.xlsx, definitions.json, eval_cases.json
scripts/ seed.py  smoke_gemini.py  ablation.py  bench_latency.py
tests/ conftest.py (FakeGemini) + test_*.py theo từng module
```

Thư viện: fastapi, uvicorn[standard], pydantic-settings, google-genai, asyncpg, numpy, pandas, openpyxl, xlrd (xls), rapidfuzz, cachetools, python-multipart, orjson; dev: pytest, pytest-asyncio, httpx. Test chạy với Postgres thật trong docker (`docker compose -f docker-compose.test.yml`) — phần thuần logic (parser, RRF, decide…) không cần DB.

---

## 11. Rủi ro

| # | Rủi ro | Mức | Giảm thiểu |
|---|---|---|---|
| R1 | `gemini-2.5-flash-lite` không truy cập được với key mới; 3.5-flash-lite luôn có thinking ≥ minimal → chậm hơn | Cao | Smoke test ngày đầu GĐ2; so latency 2 model trên cùng 50 câu |
| R2 | LLM nằm trên đường găng: p95 < 800 ms phụ thuộc mạng Oracle→Google (chưa biết region VM) | Cao | Timeout + fallback rule; cache; đo sớm từ chính VM; tuỳ chọn `UNDERSTAND_SOFT_DEADLINE`: nếu entity exact 1 sản phẩm và không có từ khoá lọc thì không chờ LLM |
| R3 | Bộ test nhỏ (80 câu): 1 câu sai = 1,25%; chỉ tiêu "matched sai < 2%" gần như = ≤1 câu → số dao động mạnh | Cao | Khuyên ≥ 150 câu/demo; báo Wilson CI; tách dev/test |
| R4 | Eval do LLM sinh → cùng "khẩu vị" với alias do LLM sinh → số đẹp ảo | Cao | Lọc rò rỉ, thêm câu manual, ưu tiên câu từ log thật khi có |
| R5 | Rate limit free tier khi chạy evaluate/ablation (hàng trăm call) | TB | concurrency thấp, cache understanding theo câu khi ablation chỉ đổi phần retrieve, dùng nhiều key |
| R6 | Số nói tiếng Việt qua ASR ("mười lăm củ", "chín triệu rưỡi", "một tỷ hai", "bốn ba in") | TB | Module `vn_numbers.py` riêng + test bảng |
| R7 | Int8 không nhanh hơn với numpy ở quy mô ~1k vector (numpy không có BLAS int8) — thực tế float32 matmul chỉ ~µs | Thấp | Giữ int8 cho baseline đúng bản cũ, đo; nếu không lợi thì dùng f32 trực tiếp (bỏ bước rescore) — quyết định bằng số |
| R8 | Kết nối LISTEN rớt → cache cũ | Thấp | Poll version 30 s + reconnect |
| R9 | Schema structured output động lớn (nhiều enum) bị từ chối | Thấp | Giới hạn enum; nếu quá lớn bỏ enum, validate ở server |
| R10 | Admin + UI mở ra Internet | TB | Admin key bắt buộc; nên đặt sau Cloudflare Tunnel/Access |

---

## 12. Câu hỏi cần bạn chốt

1. **Model LLM mặc định**: giữ `gemini-2.5-flash-lite` (nếu key bạn còn quyền) hay chuyển `gemini-3.5-flash-lite`? Tôi đề xuất: code mặc định 2.5, smoke test quyết định.
2. **Bộ test**: đồng ý tách `dev/test` và nâng lên ~150 câu/demo không? (80 là tối thiểu theo đề bài.)
3. **1 ứng viên đạt t_min nhưng chưa đạt t_match**: trả `ambiguous` với câu xác nhận ("Có phải anh/chị hỏi {tên} không ạ?") hay `no_match`? Tôi đề xuất `ambiguous` + câu xác nhận.
4. **Auth**: `X-API-Key` cho search + `X-Admin-Key` cho quản trị — ok?
5. **Seed data**: tôi tự tạo dữ liệu hư cấu nhưng thực tế (điện máy, gói cước viễn thông, căn hộ) hay bạn có file thật?
6. **Lưu `vec_f32` trong DB** (thêm ~3 KB/vector, tránh gọi lại API khi restart) — ok?
7. Thư mục `D:\Code\Senmaticsearch-tool` đang trống → tôi dựng project mới ở đây và `git init` nhé?

---

## 13. Thay đổi so với thiết kế ban đầu (phát hiện khi triển khai, 2026-10-13)

| # | Phát hiện | Thay đổi |
|---|---|---|
| 1 | `gemini-2.5-flash-lite` trả **404 "no longer available to new users"** với key hiện tại | Mặc định `gemini-3.5-flash-lite`, `thinking_level=minimal` |
| 2 | Gemini từ chối `HttpOptions.timeout` < 10s (400 "Minimum allowed deadline is 10s") | Deadline gửi server ≥ 10s; timeout ngắn thật sự cắt ở client bằng `asyncio.wait_for` |
| 3 | Free tier: embedding 100 văn bản/phút (mỗi phần tử batch = 1 request), LLM 429 sau ~20 req/phút | `EMBED_DOC_RPM`, `LLM_RPM_LIMIT`, job offline đọc `retryDelay` để chờ đúng; evaluate đo lại câu dính 429 |
| 4 | Latency LLM đo từ máy dev: understand p50 ≈ 1,5s / p95 ≈ 2,2s; rerank 1,2–2,4s | Thêm `UNDERSTAND_SOFT_DEADLINE_MS` (đi tiếp bằng rule + embedding, LLM chạy nền ghi cache); rerank chỉ viết `reason` cho top 3 |
| 5 | `cos_lo/cos_hi` cố định không hợp mọi embedding | `calibrate` học `cos_lo/cos_hi` theo demo (lưu trong `thresholds`) rồi mới fit Platt |
| 6 | Hỏi chi tiết ("cái đó bảo hành bao lâu") về đúng 1 sản phẩm lượt trước bị rơi dưới ngưỡng | `ask_detail` + 1 sản phẩm lượt trước → ghim sản phẩm đó (matched theo ngữ cảnh) |
| 7 | Rerank không có cache | Cache rerank theo (model, nội dung prompt) trong RAM + cache bền khi evaluate |
| 8 | Pickle/Alembic không cần | Migration SQL đánh số; cache bền ở bảng `llm_cache` (002) |
