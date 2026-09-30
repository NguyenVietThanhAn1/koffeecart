# KoffeeCart — Audit & kế hoạch sửa

Audit ngày 2026-09-30 trên commit `9ba572c` (main). Nguồn gốc: doc "KoffeeCart — Audit & kế hoạch sửa" trên claude.ai.

## Tóm tắt

App chạy được ở mức demo. Tuy vậy vẫn còn 1 secret đang lộ công khai, 3 lỗ hổng bảo mật đã tái hiện được, và stack Docker hiện tại phục vụ static sai. Sửa theo thứ tự Phase 0 → 3 trước khi redeploy. UI để sau cùng.

3 vấn đề nghiêm trọng nhất:

1. **Gmail app password hardcode trong `koffeecart/settings.py`**. Repo public nên ai cũng đọc được.
2. **Giả mạo thanh toán**: POST JSON `status: COMPLETED` vào `/orders/payments/` là đơn thành `is_ordered=True` và kho bị trừ, không cần qua PayPal. Đã tái hiện.
3. **IDOR**: user B xem được đơn hàng (địa chỉ, SĐT) của user A qua `/accounts/order_detail/<số đơn>/`. Đã tái hiện.

| Phase | Nội dung | Ước lượng |
| --- | --- | --- |
| 0 | Secret, repo rác, CRLF | 1 buổi |
| 1 | Docker/Nginx/scripts chạy đúng | 2–3 buổi |
| 2 | Bug + bảo mật app | 3–4 buổi |
| 3 | Test + CI/CD hoàn chỉnh | 3–4 buổi |
| 4 | Nâng cấp dependencies | 1 buổi |
| 5 | UI (tuỳ chọn, time-box) | 2–5 buổi |
| 6 | README, CV, ôn phỏng vấn | 1–2 buổi |

## Phase 0 — Khẩn cấp

Mục tiêu: repo không còn secret và chỉ chứa source code.

- [ ] (An làm tay) Thu hồi Gmail app password ở Google Account → Security → App passwords.
- [ ] Chuyển `EMAIL_HOST_USER/PASSWORD` (và `EMAIL_BACKEND`) sang `.env`. Dev dùng `django.core.mail.backends.console.EmailBackend`.
- [ ] Tạo `.env.example` chỉ có tên biến, không có giá trị thật.
- [ ] Gỡ file rác khỏi git index bằng `git rm -r --cached` (file vẫn giữ trên đĩa): `.vagrant/` (có cả `private_key`), các `__pycache__/`, `db.sqlite3`, `static/` (output của collectstatic), `media/`.
- [ ] Sửa `.gitignore`: bỏ dòng `.dockerignore` vì nó đang làm git bỏ qua một file cần commit, bỏ dòng rác `EOF`, thêm `.vagrant/` và `/static/`.
- [ ] Thêm `.gitattributes`: `* text=auto` và `*.sh text eol=lf`. Repo được clone trên Windows nên mọi file đã thành CRLF. Khi đó `deploy.sh` chạy trong VM sẽ báo `bad interpreter ^M`.
- Kiểm chứng: `git ls-files | grep -E 'vagrant|pycache|sqlite'` ra rỗng; settings.py không còn chuỗi password.

## Phase 1 — Hạ tầng chạy đúng

| # | File | Vấn đề | Cách sửa |
| --- | --- | --- | --- |
| 1 | settings.py + compose | `STATIC_ROOT = BASE_DIR/'static'`, nhưng volume và Nginx dùng `/app/staticfiles` → mọi CSS/JS 404 | `STATIC_ROOT = BASE_DIR / "staticfiles"` |
| 2 | settings.py | `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE = True` cứng → truy cập bằng HTTP qua IP VM thì CSRF 403, không login được | Đọc từ env, mặc định False |
| 3 | settings.py | `CSRF_TRUSTED_ORIGINS` hardcode Render, lại bị ghi đè khi DEBUG=False | Chỉ giữ một dòng đọc env |
| 4 | settings.py | Hack `if 'collectstatic' in sys.argv` + `':MEMORY:'` | Xoá |
| 5 | settings.py | LOGGING có 2 key `filename` và ghi log ra file | Chỉ log ra stdout |
| 6 | (thiếu) | Không có `.dockerignore` → `.git`, `.vagrant`, `db.sqlite3`, `.env` bị copy vào image | Tạo `.dockerignore` |
| 7 | Dockerfile | Chạy bằng root, cài `build-essential` thừa, `collectstatic \|\| true` nuốt lỗi, cú pháp `ENV key value` cũ | Multi-stage, user non-root, bỏ `\|\| true`, thêm HEALTHCHECK |
| 8 | compose | migrate nằm trong `command` của web | `entrypoint.sh` hoặc một service `migrate` chạy một lần |
| 9 | compose | `version:` lỗi thời; dev mount `.:/app` đè lên image; nginx không chờ web healthy | Bỏ `version`, tách `compose.override.yml` cho dev, healthcheck web bằng `/health/` |
| 10 | deploy.sh | `build --no-cache` → `down` → `up` gây downtime; in "Rolling back" nhưng không rollback | Pull image theo tag SHA, `up -d` không `down`, rollback thật về tag cũ |
| 11 | backup.sh, deploy.sh | Hardcode `/home/vagrant/...` | Dùng `$(dirname "$0")` hoặc biến môi trường |
| 12 | nginx.conf | Không gzip, không security header | Thêm gzip, `X-Content-Type-Options`, `server_name _` |
| 13 | urls.py | `/health/` trả nguyên chuỗi exception của DB | Trả `"database": "error"`, log chi tiết ở server |
| 14 | requirements | `whitenoise` được cài nhưng không dùng | Bỏ (Nginx đã phục vụ static) |

Kiểm chứng: `docker compose -f docker-compose.prod.yml up -d` → trang chủ có CSS, đăng nhập được, cả 3 service `healthy`, `docker exec koffeecart_web whoami` ≠ root.

## Phase 2 — Bug & bảo mật trong app

Mỗi dòng phải có một regression test (pytest-django).

| # | Chỗ lỗi | Kết quả test hiện tại | Cách sửa |
| --- | --- | --- | --- |
| S1 | `orders.views.payments` tin trạng thái do client gửi lên | POST giả → 200, đơn thành đã thanh toán, stock 5→4 | **An đã chọn mock/COD**: server tự quyết định số tiền, phương thức, trạng thái (`Pending`) và mã giao dịch; client chỉ gửi số đơn |
| S2 | `accounts.views.order_detail` không lọc theo user | User B đọc được đơn của A (200) | `get_object_or_404(Order, order_number=..., user=request.user)` |
| S3 | Login lấy `next` từ Referer rồi redirect thẳng | `next=https://evil.com` → 302 tới evil.com | `url_has_allowed_host_and_scheme()` |
| S4 | `place_order`, `payments`, `order_complete`, `submit_review` thiếu `@login_required` | Anonymous vào place_order → 500 | Thêm decorator; `@require_POST` cho view thay đổi dữ liệu |
| S5 | `add_cart`, `remove_cart`, `remove_cart_item` dùng GET để thay đổi dữ liệu | CSRF | Chuyển sang POST form có `{% csrf_token %}`, sửa template tương ứng |
| S6 | resetPassword/register không validate mật khẩu | Mật khẩu `a` được chấp nhận | `validate_password()` |
| S7 | Forgot password báo "Account does not exist" | Lộ email đã đăng ký | Luôn trả cùng một thông điệp |
| B1 | `add_cart` dùng `Product.objects.get` | `/cart/add_cart/9999/` → 500 | `get_object_or_404` |
| B2 | `payments` parse JSON không bắt lỗi | Body rỗng → 500 | Trả 400 |
| B3 | `resetPassword` khi session không có `uid` | 500 | Redirect về login |
| B4 | `place_order` khi form invalid trả `None` | 500 | Render lại checkout kèm lỗi |
| B5 | `submit_review` gọi `form.save()` mà không `is_valid()`; Referer có thể rỗng | 500 | Validate trước, fallback về trang sản phẩm |
| B6 | `payments` trừ kho không dùng transaction | Stock có thể âm, dữ liệu dở dang | `transaction.atomic()` + `select_for_update()` + kiểm tra đủ hàng |
| B7 | Gửi email đồng bộ, không bắt lỗi | SMTP lỗi → 500 | try/except + log |
| B8 | Tiền: `IntegerField`/`FloatField` lẫn lộn, thuế 2% copy 3 nơi | Sai số khi làm tròn | `DecimalField` (cần migration) + 1 hàm tính tổng dùng chung |
| B9 | `home` view ghi đè `reviews` trong vòng lặp; N+1 query ở `averageReview` | Kết quả sai, chậm | `annotate(Avg, Count)` |
| B10 | `carts/context_processors.py` check `'admin' in path` trong khi admin nằm ở `/securelogin/` | Query thừa | Sửa lại điều kiện path |
| B11 | `print()` debug, `import requests` chỉ để parse URL, `except: pass` | Nuốt lỗi | Dọn sạch; ruff |

## Phase 3 — Test + CI/CD

`tests.py` của cả 5 app đều rỗng. `ci.yml` hiện tại: build image 2 lần, không cache, IMAGE_NAME hardcode lệch với secret, smoke test dùng `sleep`, không có lint/test/scan/deploy.

Pipeline đích:

1. `lint`: ruff + `manage.py check --deploy`
2. `test`: pytest-django chạy với service `postgres:17`, có coverage; test cho S1–S7, B1–B6
3. `security`: pip-audit + Trivy (fail khi có CRITICAL)
4. `build-push`: build một lần, cache `type=gha`, tag `sha-<commit>` + `latest`
5. `deploy` (chỉ khi push main): self-hosted runner/SSH → `compose pull && up -d` → check `/health/` → rollback nếu fail

## Phase 4 — Dependencies

| Package | Hiện tại | Lên |
| --- | --- | --- |
| django | 5.2.7 | 5.2.17 (giữ LTS 5.2) |
| pillow | 11.3.0 | 12.3.0 |
| gunicorn | 21.2.0 | 26.x |
| requests | 2.32.5 | bỏ (dùng `urllib.parse`) |
| python-dotenv | 1.0.0 | bỏ (không dùng) |
| whitenoise | 6.6.0 | bỏ |
| psycopg2-binary | 2.9.9 | `psycopg[binary]` 3.x |
| Base image | python:3.11-slim | python:3.13-slim |
| PostgreSQL | 15-alpine | 17-alpine (DB đã có dữ liệu thì phải dump/restore) |

Tách `requirements.in`/`requirements.txt` (pip-compile hoặc uv), bật Dependabot.

## Phase 5 — UI (tuỳ chọn, làm sau cùng)

Lỗi ở `templates/base.html`: load jQuery 3 lần (file 3.3.1 không tồn tại → 404), `css/custom.css` không tồn tại → 404, Font Awesome 2 bản, PayPal SDK load ở mọi trang, Bootstrap 4 đã EOL.

Khuyến nghị: làm mới bằng Bootstrap 5.3 và giữ cấu trúc template. Việc cần làm: bỏ jQuery, đổi class BS4→BS5 (`ml-`→`ms-`, `data-toggle`→`data-bs-toggle`, `form-group`→`mb-3`), dùng CSS variables với tông màu cà phê, chỉ load PayPal ở trang thanh toán, thêm trang 404/500 riêng. Không viết lại bằng Tailwind.

## Phase 6 — README & CV

README tiếng Anh gồm: kiến trúc, cách chạy, biến môi trường, backup/restore, số liệu đo được. Ghi rõ app gốc lấy từ khoá học GreatKart. Viết `docs/incidents.md` theo format triệu chứng → nguyên nhân gốc → cách sửa → test.
