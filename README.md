# Document OCR

Ứng dụng web hỏi đáp tài liệu. Người dùng tải PDF hoặc ảnh lên, hệ thống trích
xuất văn bản bằng PDF text extraction/OCR, tìm các đoạn liên quan và dùng mô
hình OpenAI để tạo câu trả lời có ngữ cảnh từ tài liệu.

## Tính năng

- Hỗ trợ PDF, PNG, JPEG và TIFF, tối đa 100 MiB mỗi file.
- Trích xuất văn bản PDF; tự OCR trang PDF ít văn bản và OCR ảnh bằng Tesseract
  với ngôn ngữ tiếng Việt/tiếng Anh.
- Lưu file tải lên, nội dung trích xuất, ngày ban hành/ngày hiệu lực và dữ liệu
  hội thoại.
- Tìm kiếm toàn văn PostgreSQL, chuẩn hóa dấu tiếng Việt và giới hạn theo cuộc
  trò chuyện hoặc tài liệu.
- Tìm kiếm ngữ nghĩa bằng embedding `text-embedding-3-small` và pgvector, kết
  hợp với full-text search bằng Reciprocal Rank Fusion (RRF).
- Ưu tiên ngày hiệu lực/ngày ban hành khi người dùng hỏi tài liệu mới nhất.
- Chat có lịch sử, danh sách cuộc trò chuyện và lựa chọn phạm vi tài liệu.
- Ghi log ra console và `logs/`, có request ID và tự xoay vòng file log.

## Công nghệ

- Python 3.12, FastAPI, Uvicorn
- PostgreSQL 16, pgvector và SQLAlchemy
- PyMuPDF, Pillow, Tesseract OCR
- OpenAI Responses API
- Giao diện HTML/CSS/JavaScript thuần
- Docker Compose

## Chạy nhanh bằng Docker Compose

### Yêu cầu

- Docker Engine và Docker Compose plugin
- OpenAI API key

### Cài đặt và khởi chạy

```bash
cp .env.example .env

source .venv/bin/activate
uvicorn app.main:app --reload
```

Mở `.env` và cập nhật `POSTGRES_PASSWORD` cùng `OPENAI_API_KEY`. Không chia sẻ
hoặc commit file `.env`; file này chứa thông tin bí mật.

```bash
mkdir -p uploads logs
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Mở giao diện tại <http://localhost:8000>. Kiểm tra trạng thái API:

```bash
curl --fail http://localhost:8000/health
```

API docs của FastAPI có tại <http://localhost:8000/docs>.

Dừng ứng dụng mà vẫn giữ dữ liệu PostgreSQL:

```bash
docker compose down
```

Khởi động lại:

```bash
docker compose up -d
```

Không dùng `docker compose down -v` trừ khi chủ động muốn xóa volume cơ sở dữ
liệu. File upload nằm trong `uploads/`, log nằm trong `logs/`, còn PostgreSQL
được lưu trong Docker volume `postgres_data`.

## Cấu hình

| Biến | Bắt buộc | Mặc định / mô tả |
| --- | --- | --- |
| `POSTGRES_DB` | Có | Tên database PostgreSQL; mẫu là `document_ocr`. |
| `POSTGRES_USER` | Có | Tài khoản PostgreSQL; mẫu là `document_ocr`. |
| `POSTGRES_PASSWORD` | Có | Mật khẩu PostgreSQL. Hãy thay giá trị mẫu. |
| `OPENAI_API_KEY` | Có | API key dùng để tạo câu trả lời. |
| `CHAT_MODEL` | Không | Mô hình OpenAI; mặc định `gpt-4o-mini`. |
| `LOG_LEVEL` | Không | Mức log; mặc định `INFO`. |

Trong Docker Compose, `DATABASE_URL` được tạo tự động để ứng dụng kết nối tới
service `db`. Không đặt hostname database thành `localhost` khi chạy bên trong
container.

### Nếu chạy Uvicorn trực tiếp trên máy

Khi chạy `uvicorn app.main:app`, ứng dụng dùng `DATABASE_URL` trong `.env`; nó
không dùng PostgreSQL container trong Compose. PostgreSQL tại địa chỉ đó phải
được cài pgvector. Ví dụ nếu PostgreSQL trên máy là phiên bản 18:

```bash
sudo apt update
sudo apt install postgresql-18-pgvector
sudo systemctl restart postgresql
```

Database trong cấu hình hiện tại của dự án là `document_ocr_db`. Nếu cấu hình
`DATABASE_URL` của bạn khác, dùng tên database trong URL. Cài extension
vào chính database đó:

```bash
sudo -u postgres psql -d document_ocr_db \
  -c 'CREATE EXTENSION IF NOT EXISTS vector'
sudo -u postgres psql -d document_ocr_db \
  -c "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
```

Tên gói `postgresql-18-pgvector` phải khớp major version PostgreSQL đang chạy.
Nếu app chạy trong Docker Compose, không cài gói này trên host; hãy dùng image
`pgvector/pgvector:pg16` được khai báo trong `compose.yaml`.

## Luồng xử lý

1. Trong lifespan khi ứng dụng khởi động, `app.main` tạo các bảng và cập nhật
   metadata tìm kiếm/ngày tháng. Các tài liệu chưa gắn hội thoại được đưa vào
   hội thoại **Tài liệu cũ**.
2. Người dùng tạo/chọn hội thoại và tải tài liệu lên qua giao diện.
3. API kiểm tra loại file, kích thước và nội dung thực tế; sau đó xử lý PDF
   hoặc OCR ảnh/trang PDF cần thiết.
4. Văn bản được chia thành các đoạn khoảng 1.200 ký tự, có phần chồng lấn để
   giữ ngữ cảnh; mỗi đoạn được chuyển thành embedding bằng OpenAI rồi lưu cùng
   nội dung vào pgvector. Nội dung tài liệu và metadata vẫn được lưu trong
   PostgreSQL; file gốc nằm trong `uploads/`.
5. Khi nhận câu hỏi, backend tạo embedding cho câu hỏi, tìm kiếm vector theo
   cosine distance và chạy PostgreSQL full-text search. Hai thứ hạng được kết
   hợp bằng Reciprocal Rank Fusion (RRF), giới hạn theo hội thoại/tài liệu nếu
   được yêu cầu.
6. Các đoạn tìm thấy được gửi cùng câu hỏi và lịch sử hội thoại tới OpenAI.
   Câu hỏi và câu trả lời được lưu để hiển thị lại trong hội thoại.

Sau khi cập nhật từ phiên bản chưa có vector search, khởi chạy ứng dụng để tạo
bảng pgvector rồi chạy một lần lệnh sau để tạo embedding cho tài liệu đã có:

```bash
docker compose exec app python -m app.services.document_embeddings
```

Lệnh có thể chạy lại an toàn; chỉ tài liệu chưa có chunk embedding mới được xử
lý. Tạo embedding gọi OpenAI và phát sinh chi phí API, cả khi upload tài liệu,
tìm kiếm câu hỏi và chạy backfill.

## API chính

| Phương thức | Đường dẫn | Chức năng |
| --- | --- | --- |
| `GET` | `/health` | Kiểm tra ứng dụng có hoạt động. |
| `GET` | `/conversations` | Liệt kê hội thoại. |
| `POST` | `/conversations` | Tạo hội thoại mới. |
| `GET` | `/conversations/{conversation_id}` | Lấy hội thoại và tin nhắn. |
| `GET` | `/documents?conversation_id={id}` | Liệt kê tài liệu, có thể lọc theo hội thoại. |
| `POST` | `/documents/upload` | Tải tài liệu lên; nhận multipart form gồm `file` và `conversation_id` tùy chọn. |
| `GET` | `/search?q={query}` | Tìm kiếm văn bản; hỗ trợ `limit` và `conversation_id`. |
| `POST` | `/ask-document` | Tìm tài liệu và trả lời câu hỏi, không lưu lịch sử chat. |
| `POST` | `/chat` | Chat có lịch sử; có thể truyền `conversation_id` và `document_id`. |

Các endpoint nhận/trả JSON có schema và ví dụ tương tác tại `/docs`.

## Chat trên terminal

Khi API đang chạy, có thể dùng client dòng lệnh:

```bash
python -m app.chat
```

Để kết nối tới API ở địa chỉ khác:

```bash
python -m app.chat --server-url http://127.0.0.1:8000
```

Nhập `exit` hoặc `quit` để kết thúc phiên.

## Chạy kiểm thử

Trong môi trường Python đã cài các dependency từ `requirements.txt`:

```bash
python -m unittest discover -s tests
```

## Cấu trúc dự án

```text
app/
├── api/
│   ├── endpoints/                 # Router theo nhóm tính năng
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── documents.py
│   │   ├── health.py
│   │   └── search.py
│   ├── dependencies.py            # Dependency dùng chung cho API
│   └── router.py                 # Gom các endpoint router
├── core/
│   ├── logging_config.py          # Cấu hình log và request ID
│   └── middleware.py              # Request ID và log request
├── db/
│   ├── base.py                    # SQLAlchemy declarative base
│   └── session.py                 # Engine, session và get_db
├── models/                        # SQLAlchemy models, mỗi entity một file
├── schemas/                       # Pydantic schemas theo nhóm dữ liệu
├── services/
│   ├── chat_service.py            # Điều phối tìm tài liệu và chat
│   ├── conversation_migration.py  # Gắn tài liệu cũ vào hội thoại mặc định
│   ├── document_metadata.py       # Chuẩn hóa tìm kiếm, trích xuất ngày, migration
│   ├── document_embeddings.py     # Chia đoạn, tạo embedding, pgvector và backfill
│   ├── document_processor.py      # Đọc PDF và OCR ảnh/trang PDF
│   ├── llm_service.py             # Gọi OpenAI để tạo câu trả lời
│   └── search_service.py          # Tìm kiếm và chọn đoạn liên quan
├── static/
│   ├── chat.css                   # Giao diện và responsive
│   ├── chat.js                    # Tương tác web, upload và chat
│   └── index.html                 # Khung giao diện web
├── chat.py                        # Client chat trên terminal
└── main.py                        # App entrypoint, lifespan và static UI

deploy/                             # Cấu hình systemd và Nginx
tests/                              # Unit tests
uploads/                            # File tài liệu đã tải lên
logs/                               # Log ứng dụng
compose.yaml                        # PostgreSQL và ứng dụng
Dockerfile                          # Image ứng dụng và Tesseract
DEPLOY.md                           # Hướng dẫn triển khai Linux
```

Các route không chứa toàn bộ nghiệp vụ: endpoint gọi service, còn cấu hình
database nằm trong `db/`. Việc tạo bảng và migration tương thích cũ chạy trong
lifespan lúc server khởi động, không còn khi import router/module.

## Triển khai

Hướng dẫn triển khai production trên Ubuntu/Debian bằng Docker Compose,
systemd, Nginx và Certbot nằm trong [DEPLOY.md](DEPLOY.md).
