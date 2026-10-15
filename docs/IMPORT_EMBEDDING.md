# Import Excel và embedding: vận hành, kiểm tra và phục hồi

## Sự cố ngày 15/10/2026

Trên EC2, bảng `thegioinem-com` đã có 216 sản phẩm nhưng không có vector.
Job `embed_082cd8c132d2` dừng ở 34,7%, lỗi `interrupted by restart`.
Nguyên nhân trực tiếp: bản cũ giữ toàn bộ vector mới trong RAM đến cuối job;
app được rebuild/restart khi job đang chạy nên mất phần chưa commit.

Hotfix đã phục hồi cùng job lên 432/432 vector. Không reset dữ liệu, không đổi
model/số chiều, không thêm extension hay migrate schema. Các vector cũ được giữ
trong DB; index RAM bỏ qua hash không còn khớp nội dung hiện tại.

## Kiến trúc đã kiểm chứng

- Gemini SDK chính thức `google-genai`, client async `client.aio`.
- `google-genai` trên EC2: 2.31.0. API models.get trả input_token_limit=2048
  cho đúng model/tài khoản đang sử dụng (đã gọi kiểm tra trực tiếp).
- `gemini-embedding-001`, 768 chiều, L2 normalize; tài liệu dùng
  `RETRIEVAL_DOCUMENT`, câu hỏi dùng `RETRIEVAL_QUERY`.
- PostgreSQL 16 lưu `vec_int8`/`vec_f32` dưới dạng `bytea`. EC2 hiện chỉ có
  extension `plpgsql`, không có pgvector. Search chạy trên NumPy/BM25/entity
  index trong RAM, không có SQL truy vấn khoảng cách để thêm HNSW/IVFFlat.
- `EXPLAIN (ANALYZE, BUFFERS)` của truy vấn nạp hash cho catalog lỗi, ở 246
  vector trong lúc phục hồi: execution 0,398 ms; PostgreSQL dùng
  `products_demo_idx`. Đây là truy vấn nạp dữ liệu, không phải search online.
- Một worker Uvicorn. Bộ giới hạn quota và khóa job trong RAM áp dụng trong
  process này; chưa được thiết kế để chia một quota chung qua nhiều replica.

## Luồng hiện tại

1. Giới hạn file 20 MB, tối đa 10.000 dòng/256 cột; báo 413 khi quá dung lượng,
   422 khi sai định dạng/mapping/schema. Excel đọc trên thread pool 2 luồng để
   không chặn event loop HTTP. Giới hạn kích thước giải nén XLSX 100 MB.
2. Tạo bảng và nhập các dòng trong cùng transaction. Lỗi ghi rollback cả bảng
   mới; các import vào cùng bảng khóa theo bảng trước khi thay dữ liệu.
3. Job embedding được lưu trong `jobs`; cùng bảng chạy lần lượt, các bảng khác
   có thể chạy đồng thời trong giới hạn `JOB_CONCURRENCY`.
4. Batch mặc định 30 văn bản, tối đa 1 API embedding đồng thời trên provider;
   có thể cấu hình nhưng thử nghiệm 2 call đã xuất hiện một 429 nên không chọn.
   Một limiter chung
   theo provider giới hạn `EMBED_DOC_RPM` (mặc định 90 văn bản/phút). Đây là
   mức cấu hình thận trọng, không phải xác nhận quota của tài khoản Google.
5. Hash gồm model, chiều, task và nguyên văn document. Bỏ text rỗng, gộp text
   trùng trong lần chạy. Document hợp lệ được giữ nguyên, không tự chia lại
   hay truncate để tránh đổi ý nghĩa và thứ hạng search.
6. Mỗi batch hoàn tất commit bằng `executemany`, tăng `data_version` và nạp lại
   index. Không giữ connection DB trong lúc chờ API hoặc quota. Batch sau
   gọi API có thể chồng lên thao tác ghi của batch trước.
7. Restart/crash: các job embed queued/running được phục hồi cùng ID; hash đã
   có được dùng lại. Shutdown bình thường đưa job về queued trước khi đóng DB.
8. Lỗi input/vector: tách đôi batch để cô lập document lỗi, tiếp tục document
   tốt. Job kết thúc error nếu còn lỗi; `jobs.result.dead_letters` lưu
   product_id/kind/hash/reason, không lưu nội dung document. Retry chỉ embed
   phần còn thiếu. Lỗi quota/cấu hình/phiên bản bảng dừng sớm, giữ checkpoint.

Mục 8 và các timing/counter mở rộng đã qua kiểm thử và deploy lên EC2.
Đối chiếu cuối: 70 file runtime khớp local; năm file hardening trong container
khớp checksum của gói đã kiểm thử. Xem bằng chứng trong
`reports/hotfix-import-20261015/verification-final.json`.

## Quan sát và thử lại

- `GET /v1/admin/jobs/{id}`: status, progress và result/checkpoint.
- `POST /v1/admin/jobs/{id}/retry`: chỉ nhận job embed error/cancelled; trả job_id.
- Giao diện tự tìm job đang chạy sau khi tải lại trang, hiển thị số vector đã
  lưu; job lỗi có nút **Tiếp tục phần vector còn thiếu**.
- `timing_ms`: plan, tổng/mean API call, quota wait, DB write, wall.
  API timing ở đây bao gồm retry nội bộ; nó không phải latency của mỗi HTTP
  attempt. Các thời gian cộng qua worker có thể lớn hơn wall do chạy song song.
- `/health?full=true`: thống kê provider và counter HTTP lỗi khi có quyền admin.
  Token embedding hiện là ước lượng theo độ dài ký tự do SDK đang cài không
  trả token usage tương ứng; không dùng con số này để xuất hóa đơn.
- Retry 429 đọc retryDelay, 5xx/timeout/transport dùng backoff có jitter,
  số lần hữu hạn. Không retry API 400 như lỗi mạng; chỉ tách batch để xác định
  document sai. Các lệnh DB có timeout và lock timeout ở bản hardening.

## Kiểm thử và benchmark

```bash
python -m pytest tests/test_ingest_recovery.py tests/test_vectors.py tests/test_tables.py -q
python -m pytest -q
python -m scripts.bench_ingest --label after --products 90 --batch 30 --concurrency 1
```

Benchmark gọi Gemini thật trên 90 sản phẩm synthetic/180 document. Ghi catalog
được chặn và giữ trong RAM, chỉ dùng bảng TEMP theo session để đo ghi DB. Không
ghi vào catalog/job hiện có. Search đo 6 tên sản phẩm chính xác ở `mode=fast`,
trong process, không bao gồm HTTP và không đại diện mọi câu ASR. Khoảng mẫu
nhỏ; không dùng p95 này để cam kết SLA. Để ít nhất 60 giây giữa hai phép đo dùng
cùng quota; probe hỗ trợ tối đa 2, cấu hình vận hành chọn 1.

## Rollback hotfix EC2

Backup chỉ lưu trên EC2 ở `/home/ec2-user/semsearch-backups/import-fix-20261015/`:
`code-before.tar.gz`, `database-before.sql`. Image cũ có tag
`sematicsearch-ai-app:before-import-fix-20261015`. Không tự restore dump DB;
dump là phương án cuối và cần xác nhận vì có thể ghi đè thay đổi mới.

Rollback code sau khi các job cần giữ đã hoàn tất:

```bash
cd /home/ec2-user/sematicsearch-ai
tar -xzf /home/ec2-user/semsearch-backups/import-fix-20261015/code-before.tar.gz
sudo docker image tag sematicsearch-ai-app:before-import-fix-20261015 sematicsearch-ai-app:latest
sudo docker compose up -d --no-deps --no-build app
curl -fsS http://127.0.0.1:8000/health
```

Rollback này giữ nguyên DB và vector đã commit, không có migration cần đảo.

## Các lựa chọn chưa tự áp dụng

- Không đổi model, chiều, chunk hay công thức search. Chia theo 200–500 token
  cần tập đánh giá so sánh trước khi phê duyệt; không thể đảm bảo bằng số ký tự.
- Không thêm pgvector/index; không liên quan đường search RAM hiện tại. Nếu
  chuyển kiến trúc, cần benchmark và script migration/rollback riêng. Tham số
  HNSW/IVFFlat không áp dụng cho cột `bytea` hiện có.
- API đồng bộ nhận nhiều text đã được dùng. Tài liệu REST hiện có
  `asyncBatchEmbedContent` riêng cho xử lý nền; cần kiểm tra quyền/quota/giá
  thực của tài khoản trước khi tích hợp. Không tự bật billing hay chuyển API.
- Trang Batch API chung ghi thời gian mục tiêu 24 giờ và giá bằng 50% API
  tương ứng nhưng hiện có ghi chú phạm vi generateContent. Không suy mức giá
  hay thời gian này thành cam kết cho embedding của tài khoản đang dùng.
- API reference được kiểm tra có phương thức batch nhưng không nêu rõ trần
  số văn bản cho endpoint này; giữ 30 đã chạy thật. `100` trong helper là chặn
  nội bộ có sẵn, không được coi là giới hạn Gemini đã xác minh.

Nguồn chính thức (đối chiếu 15/10/2026):

- [Embedding API reference](https://ai.google.dev/api/embeddings)
- [Embedding và normalization](https://ai.google.dev/gemini-api/docs/embeddings)
- [Batch API và phạm vi hỗ trợ](https://ai.google.dev/gemini-api/docs/batch-api)
