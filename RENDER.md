# Deploy: Render (app) + Neon (Postgres) — miễn phí, không cần thẻ

## 1. Tạo database Neon (free)
1. Đăng ký https://neon.tech bằng email/Google (không cần thẻ) → tạo project.
2. Vào **Connection string**, chọn endpoint **Direct connection** (KHÔNG chọn "Pooled/-pooler").
3. Copy chuỗi dạng: `postgresql://user:pass@ep-xxx.<region>.aws.neon.tech/neondb?sslmode=require`

## 2. Đưa code lên GitHub
Repo cần nằm trên GitHub để Render deploy:
```bash
git add -A && git commit -m "deploy render"
git remote add origin https://github.com/<ban>/<repo>.git   # tạo repo trống trên GitHub trước
git push -u origin main
```

## 3. Tạo Render service (free)
1. Đăng ký https://render.com bằng GitHub (không cần thẻ).
2. **New → Blueprint** → chọn repo này (Render đọc `render.yaml`), hoặc **New → Web Service → Docker**.
3. Điền biến môi trường (các key `sync:false`):
   - `GEMINI_API_KEY` = key Gemini của bạn
   - `DATABASE_URL` = chuỗi Neon ở bước 1
   - `SEED_ACCOUNT_PASSWORD` = mật khẩu mạnh cho tài khoản quản trị
4. **Deploy**. Render build Dockerfile, chạy ở cổng động, health check `/health`. Migrations + tài khoản admin tự tạo.

## 4. Nạp dữ liệu
- **Dữ liệu mẫu**: Render → service → **Shell**: `python -m scripts.seed --reset`
- **Mang dữ liệu hiện tại** (THEGIOINEM.COM + tài khoản + khoá) từ máy bạn vào Neon:
  1. `bash scripts/dump_local.sh` → tạo `reports/semsearch_dump.sql`
  2. Nạp vào Neon từ máy bạn: `psql "<chuỗi-Neon>" < reports/semsearch_dump.sql`
  3. Restart service trên Render để nạp lại cache.

## Lưu ý Render free
- Web **ngủ sau 15 phút** không có request → lần gọi đầu chậm ~30–50s để thức. Gọi `/health` định kỳ (cron-job.org free) để giữ thức nếu cần.
- RAM 512MB, 0.1 CPU — đủ cho app (không có model local). Neon free tự ngủ khi rảnh, query đầu tiên đánh thức (~1s).
- Đổi `SEED_ACCOUNT_PASSWORD` mạnh vì app công khai Internet.
