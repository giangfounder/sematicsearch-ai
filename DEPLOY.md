# Deploy lên server thật (luôn bật)

> Môi trường đang sử dụng: AWS EC2 (Amazon Linux 2023), Docker Compose.
> Xem [vận hành và phục hồi import/embedding](docs/IMPORT_EMBEDDING.md).
> Các bước Oracle bên dưới là hướng dẫn cũ, không phản ánh cấu hình EC2 hiện tại.

## Giao diện Svelte + Tailwind

Nguồn nằm trong `frontend/`; xem [hướng dẫn frontend](frontend/README.md).
`docker compose build app` tự build UI bằng Node ở stage riêng; image chạy thực tế chỉ có Python.
Khi deploy thủ công, luôn cập nhật đồng bộ `app/static/index.html`, assets đi kèm và
`app/main.py` (phục vụ `/assets`, gzip và cache). Không chỉ copy riêng HTML.
Trước khi thay image, gắn tag image đang chạy để rollback; không cần đổi schema,
xoá dữ liệu hay tạo lại vector cho cập nhật UI này.

Project đóng gói Docker đa kiến trúc (amd64 + arm64), chạy bằng **một lệnh** trên bất kỳ server nào có Docker.
Khuyến nghị server **miễn phí, luôn bật**: **Oracle Cloud Always Free** (VM.Standard.A1.Flex ARM, 4 OCPU / 24GB,
free vĩnh viễn). Dùng được mọi VPS khác (DigitalOcean, Hetzner, AWS Lightsail…).

## 1. Chuẩn bị server
- Tạo VM Ubuntu 22.04 (Oracle: chọn Ampere A1, Always Free).
- Mở cổng 8000 (hoặc 80/443 nếu dùng reverse proxy): **Oracle chặn 2 lớp** — mở ở Security List (web console)
  VÀ trong máy: `sudo iptables -I INPUT 6 -p tcp --dport 8000 -j ACCEPT && sudo netfilter-persistent save`.
- Cài Docker: `curl -fsSL https://get.docker.com | sh`

## 2. Đưa code + cấu hình lên
```bash
git clone <repo>  # hoặc scp cả thư mục dự án lên server
cd Senmaticsearch-tool
cp .env.prod.example .env
nano .env          # điền GEMINI_API_KEY, đổi mật khẩu DB + tài khoản admin
```

## 3. Chạy
```bash
docker compose up -d --build
docker compose logs -f app      # xem log khởi động
```
App chạy ở `http://<IP-server>:8000`. Migrations + tài khoản admin tự tạo khi khởi động.

## 4. Nạp dữ liệu
- **Dữ liệu mẫu**: `docker compose exec app python -m scripts.seed --reset`
- **Mang dữ liệu hiện tại từ máy bạn** (gồm bảng THEGIOINEM.COM, tài khoản, khoá):
  1. Trên máy dev: `bash scripts/dump_local.sh` → tạo `reports/semsearch_dump.sql`
  2. Copy file lên server, rồi: `docker compose exec -T db psql -U semsearch semsearch < semsearch_dump.sql`
  3. `docker compose restart app` để nạp lại cache.

## 5. HTTPS (khuyến nghị cho callbot)
Dùng Caddy trước app (tự cấp chứng chỉ Let's Encrypt), hoặc Cloudflare Tunnel có tên nếu có domain.
Thêm service `caddy` vào docker-compose với domain trỏ về server.

## Lưu ý
- Mật khẩu mặc định YẾU — đổi `SEED_ACCOUNT_PASSWORD` và `POSTGRES_PASSWORD` trước khi mở ra Internet.
- 1 worker (model/cache trong RAM). Muốn nhiều worker: bỏ cache response chung hoặc dùng Redis (chưa cần ở quy mô này).
