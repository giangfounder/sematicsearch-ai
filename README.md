# Product Semantic Search (callbot / chatbot tiếng Việt)

Backend nhận **1 câu nói tự nhiên** (output ASR có từ đệm, nghe nhầm, không dấu) + ngữ cảnh hội thoại và trả
**top k sản phẩm** kèm **trạng thái quyết định** (`matched | ambiguous | no_match | out_of_scope`) và câu hỏi làm rõ.
Ưu tiên 1 là độ chính xác (thà hỏi lại còn hơn trả sai), ưu tiên 2 là latency.

Thiết kế chi tiết: [docs/DESIGN.md](docs/DESIGN.md).

## Kiến trúc tóm tắt

```
câu -> chuẩn hoá (NFC, bỏ từ đệm, số đọc thành chữ -> số) -> cache?
    -> entity linking + rule parser (RAM, vài ms)
    -> song song: Gemini hiểu câu (structured output) | Gemini embedding câu hỏi
    -> lọc cứng (chỉ ràng buộc explicit + filterable, có nới dần) -> dense Int8 đa vector + BM25 + entity -> RRF
    -> chấm lại cosine float32 -> điểm tổng hợp (Platt) -> gating -> [Gemini rerank] -> quyết định -> response
```

- PostgreSQL là nguồn gốc; search nóng chạy hoàn toàn trên cache RAM (`DemoIndex`), không query DB.
- Mọi thay đổi dữ liệu tăng `data_version` → `NOTIFY demo_changed` → nạp lại index (atomic swap) + poll 30s dự phòng.
- Không có model local (không torch) → image `python:3.11-slim` chạy thẳng trên ARM64 (Oracle A1).

## Chạy local

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/mac: .venv/bin/pip
cp .env.example .env    # điền GEMINI_API_KEY
```

Không có Docker? Dùng Postgres nhúng (gói `pgserver`):

```bash
python -m scripts.local_pg --create      # in ra DATABASE_URL, chép vào .env
python -m scripts.seed --reset           # nạp 3 demo mẫu + embed (free tier: ~10 phút)
uvicorn app.main:app --port 8000         # UI test: http://localhost:8000/
```

Có Docker: `docker compose up -d --build` rồi `docker compose exec app python -m scripts.seed --reset`.

Chạy offline không cần key: `GEMINI_PROVIDER=fake` (embedding băm n-gram, LLM giả) — **chỉ để test luồng**,
con số độ chính xác chỉ có ý nghĩa với Gemini thật.

## Biến môi trường chính

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `GEMINI_API_KEY` | | nhiều key cách nhau `,` → xoay vòng khi 429 |
| `GEMINI_LLM_MODEL` / `GEMINI_RERANK_MODEL` | `gemini-3.5-flash-lite` | `gemini-2.5-flash-lite` trả 404 với tài khoản mới (đã kiểm tra) |
| `GEMINI_THINKING_LEVEL` | `minimal` | model 3.x không tắt hẳn được thinking |
| `GEMINI_EMBED_MODEL`, `EMBED_DIM` | `gemini-embedding-001`, 768 | tự L2-normalize (bắt buộc khi khác 3072) |
| `UNDERSTAND_TIMEOUT_MS` / `EMBED_TIMEOUT_MS` / `RERANK_TIMEOUT_MS` | 1200 / 800 / 2500 | timeout phía client; deadline gửi server luôn ≥10s (Gemini từ chối deadline <10s) |
| `UNDERSTAND_SOFT_DEADLINE_MS` | 0 (tắt) | >0: không chờ LLM quá mốc này khi không có ngữ cảnh; LLM chạy nền để ghi cache |
| `API_KEYS` / `ADMIN_KEYS` | trống = mở | **bắt buộc đặt `ADMIN_KEYS` khi deploy** |
| `EMBED_DOC_RPM` | 90 | free tier embedding = 100 văn bản/phút (mỗi văn bản trong batch tính 1 request) |
| `LLM_RPM_LIMIT` | 0 | giới hạn request LLM/phút; đặt ~12 khi chạy evaluate trên free tier |
| `PERSISTENT_CACHE_ONLINE` | false | cache bền (Postgres) embedding/understanding cho search online |

## API

`POST /v1/demos/{slug}/search` (header `X-API-Key`)

```json
{"text": "dạ cho em hỏi tủ lạnh sam sung tầm 10 củ loại tiết kiệm điện", "top_k": 3, "mode": "auto",
 "context": {"previous_text": null, "previous_product_ids": [], "previous_filters": null}, "debug": false}
```

Response (hợp đồng cố định, chỉ được THÊM field): `request_id, status, clarify_question, products[{rank, product_id,
sku, name, price, price_unit, in_stock, score, confidence, reason, attributes[{key,label,value,unit,display}], data}],
understanding{intent, rewritten_query, filters, entities}, relaxed, relaxed_keys, reranked, cache_hit,
fallback_reason, latency_ms{total, understand, embed, retrieve, rerank}` (+ `data_version`, `debug` khi debug=true).

- `mode`: `fast` (không rerank) | `auto` (gating) | `accurate` (luôn rerank).
- `fallback_reason`: `understand_timeout|understand_error|understand_rate_limited|understand_deferred|embed_*|rerank_*`.
  Kết quả có fallback không được cache.
- Bot nên truyền lại `understanding.filters` của lượt trước vào `context.previous_filters` để tinh chỉnh nhiều lượt.

`POST /v1/search/{request_id}/feedback` `{correct, correct_product_id?, add_to_eval?}` → lưu log, tuỳ chọn tạo eval_case.

Quản trị (`X-Admin-Key`): `/v1/admin/demos` (CRUD), `/definitions`, `/products`, `/import` (multipart, `dry_run`),
`/template.xlsx`, `/embed`, `/enrich` (+ `/enrich/{job}/apply`), `/eval_cases` (+ `/generate`), `/jobs/{id}`,
`/logs`, `/v1/admin/usage`; `POST /v1/demos/{slug}/evaluate`, `POST /v1/demos/{slug}/calibrate`. `GET /health?full=true`.

## Bảng dữ liệu (tích hợp nhanh từ Excel)

Portal tab **"Bảng dữ liệu"**: tải Excel/CSV → xem trước, chọn cột tên / cột mã → "Tạo bảng + embedding" →
portal sinh sẵn cURL. Mỗi bảng là 1 demo (dùng chung pipeline search); hệ thống nhớ tên cột của file đầu tiên
nên API thêm/sửa dùng đúng các cột đó và trả về **nguyên dòng gốc** (đúng tên + thứ tự cột).

```bash
# hỏi bằng câu tự nhiên -> 1 row  (X-API-Key)
curl -X POST "$BASE/v1/tables/goi-cuoc/ask" -H 'Content-Type: application/json' -H "X-API-Key: $KEY" \
  -d '{"text": "gói cho cả nhà dùng chung"}'
# -> {"found":true,"status":"matched","row":{"Mã gói":"G4","Tên gói":"Gói Gia Đình 300",...},"score":0.88,
#     "row_key":"G4","clarify_question":null,"alternatives":[...],"latency_ms":...}

# thêm mới / cập nhật (trùng mã = cập nhật), tự embed lại phần đổi  (X-Admin-Key)
curl -X PUT "$BASE/v1/tables/goi-cuoc/rows" -H 'Content-Type: application/json' -H "X-Admin-Key: $ADMIN" \
  -d '{"rows":[{"Mã gói":"G7","Tên gói":"Gói Sinh Viên Đêm","Giá (đồng/tháng)":30000}], "mode":"upsert"}'

# xoá dòng theo mã
curl -X DELETE "$BASE/v1/tables/goi-cuoc/rows" -H 'Content-Type: application/json' -H "X-Admin-Key: $ADMIN" \
  -d '{"keys":["G7"]}'
```

### Khoá API riêng cho từng bảng

Portal tab **"Khoá API"** (hoặc `/v1/tables/{slug}/keys`, cần khoá quản trị toàn cục): tạo khoá chỉ dùng được cho
đúng bảng đó, quyền `read` (gọi `/ask`) hoặc `read,write` (gọi `/rows`). Khoá gửi qua header `X-API-Key` hoặc
`X-Table-Key`. Server chỉ lưu `sha256(khoá)`; khoá gốc hiện **một lần** khi tạo. Bảng nào đã có khoá đang hoạt động
thì mọi lời gọi tới bảng đó phải kèm khoá hợp lệ; khoá quản trị toàn cục vẫn gọi được mọi bảng. Khi bảng chưa có
khoá riêng và server không đặt `API_KEYS`/`ADMIN_KEYS`, API mở (chế độ dev).

```
GET/POST /v1/tables/{slug}/keys · PATCH/DELETE /v1/tables/{slug}/keys/{id}
POST body: {"name","scopes":["read"|"write"],"expires_days"?}  → trả {"key": "sk_tbl_…", ...} đúng một lần
```

`found=false` khi chưa đủ chắc (`ambiguous`/`no_match`/`out_of_scope`) → bot đọc `clarify_question` hoặc câu fallback.
Quản lý: `GET /v1/tables`, `POST /v1/tables/preview` (multipart), `POST /v1/tables` (multipart: file, name, slug,
mapping), `GET /v1/tables/{slug}/rows?q=&offset=&limit=`, đổi tên `PATCH /v1/admin/demos/{slug}`, xoá
`DELETE /v1/admin/demos/{slug}`. Không có cột mã → khoá sinh từ tên (`goi_a`, `goi_a-2`).

## Quy trình đưa 1 catalog mới vào

1. `POST /v1/admin/demos` tạo demo.
2. `POST .../import` với `dry_run=true` → xem `proposed_definitions` (type/unit tự suy), `preview`, `warnings`;
   sửa definitions rồi gửi lại với `dry_run=false` + `definitions=<json>` → tự chạy job embed.
3. `POST .../enrich` (dry_run) → duyệt trên UI tab "Duyệt enrichment" → apply (tự re-embed phần đổi).
4. Thêm eval_cases: viết tay, `POST .../eval_cases/generate` (LLM, có lọc rò rỉ so với câu hỏi mẫu), hoặc từ feedback.
5. `POST /v1/demos/{slug}/calibrate` (split=dev) → lưu ngưỡng; `evaluate` (split=test) để báo số.

## Công thức điểm (app/search/scoring.py) và ý nghĩa hệ số

| Tín hiệu | Tính thế nào | Hệ số mặc định |
|---|---|---|
| `cos` | max theo loại vector `w_kind * cos(query, vector)`; `w = question 1.0, name 0.97, use_case 0.93, profile 0.90` (câu hỏi mẫu gần văn nói nhất). Chuẩn hoá `(cos - cos_lo)/(cos_hi - cos_lo)` | 0.45 |
| `rrf` | `Σ w_s/(k + rank_s)` trên dense, BM25, entity; `k=20` (catalog nhỏ, k=60 làm phẳng quá), `w = dense 1.0, bm25 0.8, entity 1.5`; chia cho giá trị tối đa | 0.20 |
| `entity` | 1.0 khớp chính xác tên/alias/SKU/mã model (không dấu), `ratio/100` nếu fuzzy, ×0.6 nếu bề mặt dùng chung nhiều sản phẩm | 0.20 |
| `soft` | tỷ lệ ràng buộc thoả theo `weight` thuộc tính (giá gần mức "tầm", đúng hãng mong muốn, bool…) | 0.10 |
| `stock`, `prev` | còn hàng; nằm trong sản phẩm lượt trước khi tinh chỉnh | 0.03, 0.02 |

`final = sigmoid(A·raw + B)` — `A, B` (Platt), `cos_lo/cos_hi` học bằng `calibrate` trên split dev của từng demo
(cos_lo ≈ trung vị cosine ứng viên sai, cos_hi ≈ phân vị 75 ứng viên đúng) → `final` xấp xỉ xác suất top-1 đúng nên
ngưỡng có cùng ý nghĩa giữa các demo. Khi rerank: `score = (1-β)·final + β·relevance`, ×0.6 nếu vi phạm ràng buộc nói rõ.

Quyết định: `matched` nếu `s1 ≥ t_match` và (`s1 - s2 ≥ margin` hoặc entity khớp chính xác 1 sản phẩm);
`no_match` nếu `s1 < t_min`; còn lại `ambiguous` + `clarify_question` sinh từ thuộc tính phân biệt các ứng viên sát
điểm (ưu tiên filterable → weight cao → ít lựa chọn). 1 ứng viên duy nhất chưa đủ chắc → câu xác nhận
"Có phải anh/chị đang hỏi … không ạ?". Mọi hệ số override được theo demo qua `demos.settings.scoring`.

## Đánh giá

- `POST /v1/demos/{slug}/evaluate`: hit@1, hit@3, MRR, độ chính xác status + ma trận nhầm lẫn, **tỷ lệ matched-sai**
  (kèm khoảng tin cậy Wilson 95% vì n nhỏ), tỷ lệ rerank/fallback, latency p50/p95 từng bước, câu sai + debug,
  gợi ý sản phẩm cần thêm alias. Evaluate dùng cache bền cho embedding/understanding/rerank nên chạy lại rẻ;
  câu dính 429 (quota) được đợi và đo lại.
- `python -m scripts.ablation --demo dienmay` → `reports/ablation_<demo>_<split>.md`: B0 (giống bản Apps Script cũ)
  → thêm từng thành phần → rerank; và "full bỏ từng phần".
- `python -m scripts.bench_llm` so latency model/thinking; `python -m scripts.smoke_gemini` kiểm tra key/model.

Dữ liệu mẫu (`seeds/`, dựng bằng `seeds/src/*.py`): điện máy 47 sp / 162 câu, viễn thông 32 / 123, bất động sản
30 / 112. Câu đánh giá sinh từ mẫu KHÁC mẫu câu hỏi dùng để embed + nhiễu ASR (phiên âm tên ngoại, sai thanh,
số đọc thành chữ, bỏ dấu) + câu viết tay (công dụng, nhiều lượt, mơ hồ, ngoài phạm vi). Tách 40% dev / 60% test.
Giá và dự án đều hư cấu.

## Test

```bash
pytest -q        # Postgres thật (pgserver tự khởi động) + Gemini giả; không gọi API thật
```

## Deploy Oracle Cloud A1 (ARM64)

1. VM Ubuntu, cài Docker; `git clone`; tạo `.env` (đặt `ADMIN_KEYS`, `API_KEYS`, `POSTGRES_PASSWORD`,
   `DATABASE_URL=postgresql://semsearch:<pw>@db:5432/semsearch`).
2. `docker compose up -d --build` (image không có torch nên build trên ARM nhanh).
3. Mở cổng: Security List trên web **và** iptables trong máy
   (`sudo iptables -I INPUT 6 -p tcp --dport 8000 -j ACCEPT && sudo netfilter-persistent save`) —
   hoặc dùng **Cloudflare Tunnel** (không cần mở cổng, có HTTPS + domain; có thể đặt Cloudflare Access trước admin).
4. `docker compose exec app python -m scripts.smoke_gemini` để đo latency thật từ region của VM.

## Giới hạn đã biết

- Latency LLM là nút cổ chai (đo từ máy dev: understand p50 ≈1,5s, rerank 1,2–2,4s với gemini-3.5-flash-lite) —
  xem `reports/` và mục Latency trong báo cáo; `UNDERSTAND_SOFT_DEADLINE_MS` đánh đổi một phần độ chính xác lấy latency.
- Free tier: embedding 100 văn bản/phút; LLM bị 429 sau ~20 request/phút → cần paid tier cho môi trường thật.
- Chạy 1 worker (cache response trong RAM dùng chung); nhiều worker vẫn đúng (mỗi worker LISTEN và nạp index riêng).
