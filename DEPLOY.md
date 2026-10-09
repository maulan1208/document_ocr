# Triển khai Document OCR trên Linux

Hướng dẫn này dùng Ubuntu/Debian, Docker Compose, PostgreSQL, systemd và Nginx. API chỉ bind vào `127.0.0.1:8000`; chỉ Nginx được mở ra Internet. PostgreSQL dùng Docker volume, còn file upload và log được lưu trong `uploads/` và `logs/`.

## 1. Chuẩn bị server

Trỏ bản ghi DNS `A` (và `AAAA` nếu có) của domain về IP server. Mở các cổng SSH, HTTP và HTTPS trên firewall của nhà cung cấp VPS.

Cài Docker Engine cùng plugin Docker Compose theo hướng dẫn chính thức của Docker cho bản Ubuntu/Debian đang dùng. Cài Nginx và Certbot:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
docker --version
docker compose version
```

Các lệnh Docker cần quyền truy cập Docker daemon. Nếu user deploy chưa được cấp quyền, thêm `sudo` trước lệnh `docker`; quyền trong group `docker` tương đương quyền root trên server.

## 2. Đưa source lên server

Có thể clone repo vào đúng đường dẫn mà systemd unit đang dùng:

```bash
sudo mkdir -p /opt/document-ocr
sudo chown "$USER":"$USER" /opt/document-ocr
git clone <repository-url> /opt/document-ocr
cd /opt/document-ocr
```

Hoặc đồng bộ source từ máy phát triển; không gửi `.env`, virtualenv, log hay dữ liệu upload:

```bash
rsync -av \
  --exclude .env \
  --exclude .venv/ \
  --exclude uploads/ \
  --exclude logs/ \
  ./ <user>@<server>:/opt/document-ocr/
```

## 3. Tạo `.env`

```bash
cd /opt/document-ocr
cp -n .env.example .env
openssl rand -hex 24
nano .env
chmod 600 .env
```

`cp -n` giữ nguyên `.env` nếu đã có; khi đó chỉ bổ sung/cập nhật các biến `POSTGRES_*`, `OPENAI_API_KEY`, `CHAT_MODEL` và `LOG_LEVEL` cần thiết. Đặt đầu ra của `openssl rand -hex 24` làm `POSTGRES_PASSWORD`, thay `OPENAI_API_KEY` bằng key thật. Không commit hoặc gửi `.env` lên Git. Compose tự tạo `DATABASE_URL` trỏ tới service `db`; không dùng `localhost` làm hostname PostgreSQL bên trong container.

## 4. Khởi chạy Docker Compose

```bash
mkdir -p uploads logs
sudo chown -R 10001:10001 uploads logs
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Kiểm tra `app` và `db` ở trạng thái khỏe mạnh trước khi cấu hình Nginx. Ứng dụng cần `OPENAI_API_KEY` ngay khi khởi động; nếu thiếu hoặc sai, xem log app.

Khi khởi động, ứng dụng tự tạo cấu trúc lưu cuộc trò chuyện/tin nhắn, bật
extension pgvector và gán các tài liệu đã có vào cuộc trò chuyện **Tài liệu cũ**.
Nên sao lưu database trước khi cập nhật ứng dụng lần đầu có thay đổi này. Cơ sở
dữ liệu dùng image `pgvector/pgvector:pg16`.

Nếu nâng cấp từ phiên bản chưa lưu embedding, sau khi app và database đã khỏe
mạnh, chạy backfill một lần:

```bash
docker compose exec app python -m app.services.document_embeddings
```

Lệnh chỉ xử lý tài liệu chưa có chunk embedding và có thể chạy lại an toàn. Việc tạo embedding gọi OpenAI và phát sinh chi phí API.

Nếu ứng dụng báo lỗi `The extension must first be installed on the system where PostgreSQL is running`, nó đang kết nối tới PostgreSQL không có pgvector. Với Compose, kiểm tra image database và tạo lại container mà không xóa volume:

```bash
docker compose pull db
docker compose up -d --force-recreate db
docker compose ps
docker compose up -d --build --force-recreate app
```

Không chạy `docker compose down -v`. Nếu chạy Uvicorn trực tiếp trên host, cần
cài gói pgvector cho đúng major version PostgreSQL mà `DATABASE_URL` trỏ tới,
sau đó restart PostgreSQL và tạo extension trong database ứng dụng:

```bash
sudo apt install postgresql-<POSTGRES_MAJOR>-pgvector
sudo systemctl restart postgresql
sudo -u postgres psql -d ten_database_cua_ban \
  -c 'CREATE EXTENSION IF NOT EXISTS vector'
```

Thay `POSTGRES_MAJOR` bằng major version PostgreSQL và `ten_database_cua_ban`
bằng database được cấu hình trong `DATABASE_URL`.

## 5. Quản lý bằng systemd

Unit có trong `deploy/document-ocr.service` và giả định project nằm tại `/opt/document-ocr`:

```bash
sudo cp deploy/document-ocr.service /etc/systemd/system/document-ocr.service
sudo systemctl daemon-reload
sudo systemctl enable --now document-ocr
sudo systemctl status document-ocr
```

Compose đã đặt `restart: unless-stopped`; Docker tự khởi động lại container sau reboot. systemd giúp khởi chạy/dừng stack theo service:

```bash
sudo systemctl restart document-ocr
sudo systemctl stop document-ocr
sudo systemctl start document-ocr
```

Sau khi cập nhật source, chạy `docker compose up -d --build` trong `/opt/document-ocr`. Nếu cài Docker ở đường dẫn khác `/usr/bin/docker`, cập nhật `ExecStart` và `ExecStop` trong unit rồi chạy `systemctl daemon-reload`.

## 6. Cấu hình Nginx reverse proxy

```bash
sudo cp deploy/nginx-site.conf /etc/nginx/sites-available/document-ocr
sudo nano /etc/nginx/sites-available/document-ocr
```

Thay `example.com` và `www.example.com` bằng domain thật, sau đó bật site:

```bash
sudo ln -s /etc/nginx/sites-available/document-ocr /etc/nginx/sites-enabled/document-ocr
sudo nginx -t
sudo systemctl reload nginx
```

Nếu UFW đang dùng, cho phép SSH trước khi bật firewall để tránh tự khóa khỏi server:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw status
```

Sau khi DNS đã trỏ đúng và HTTP hoạt động, bật HTTPS:

```bash
sudo certbot --nginx -d example.com -d www.example.com
sudo certbot renew --dry-run
```

Nginx cho phép request lớn hơn giới hạn upload 100 MiB của API để tính phần multipart. Timeout dài hơn để OCR tài liệu lớn có thời gian hoàn tất.

## 7. Log và kiểm tra lỗi

```bash
cd /opt/document-ocr
docker compose logs --tail=100 app
docker compose logs -f app
tail -f logs/app.log
tail -f logs/error.log
sudo journalctl -u document-ocr -n 100 --no-pager
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

App ghi ra console và file; file log tự rotate ở 5 MiB, giữ 5 bản sao cho mỗi log. Docker JSON log giới hạn 10 MiB x 3 file/container.

## 8. Cập nhật và backup

Cập nhật app:

```bash
cd /opt/document-ocr
git pull
docker compose up -d --build
docker compose ps
```

Backup PostgreSQL dạng SQL:

```bash
cd /opt/document-ocr
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "backup-$(date +%F-%H%M%S).sql"
```

Sao lưu thư mục `uploads/` cùng bản dump cơ sở dữ liệu sang nơi lưu trữ khác server. Docker volume không thay thế backup. Để khôi phục file SQL vào database đang chạy:

```bash
cat <backup-file.sql> | docker compose exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Không chạy `docker compose down -v` trừ khi chủ động muốn xóa cả dữ liệu PostgreSQL.
