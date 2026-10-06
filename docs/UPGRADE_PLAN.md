# KoffeeCart — Kế hoạch nâng cấp (sau Phase 0–3)

Audit ngày 2026-10-04 trên commit `edd5171` (main) cộng với phần Phase 3 đang nằm trong working tree, chưa commit.
File này nối tiếp [FIX_PLAN.md](FIX_PLAN.md): giữ nguyên thứ tự Phase 4 → 6, bổ sung Phase 4B (bug còn sót) và Phase 7 (DevOps nâng cao, tuỳ chọn).

## 0. Tiến độ

| Phase | Trạng thái |
| --- | --- |
| 3.9 | Xong: commit `982b007` trên nhánh `upgrade/phase-3-7` |
| 4 | Xong (xem commit "Phase 4") |
| 4B | Xong: 17 regression test mới (fail trước khi sửa, pass sau). Kèm 2 lỗi phát hiện thêm trong admin (xem commit "Phase 4B") |
| 5 | Xong: Bootstrap 5.3.8 (tải từ npm, đối chiếu sha512), bỏ jQuery/BS4/PayPal SDK, CSP, logout bằng POST, trang 404/500. Static 8,3 MB → 0,9 MB. Đã chạy thử luồng mua hàng trên trình duyệt |
| 6 | Xong: `seed_demo` (ảnh vẽ bằng Pillow, chạy lại không tạo trùng, có test), README tiếng Anh, `docs/incidents.md`. Đã nạp dữ liệu mẫu vào `db.sqlite3` local (bản sao lưu: `db-backup-2026-10-06-before-upgrade.sqlite3`) |
| 7 | Đang làm |

Quyết định An đã chốt ngày 2026-10-06: **Python 3.14** (D1), **`uv pip compile`** (D2), VM **không có dữ liệu cần giữ** (D3, chỉ cần `down -v` rồi `up`), **không có domain** (D4), Phase 7 để Claude chọn (D5), An sẽ tự thu hồi Gmail app password (D6). Máy An tắt ảo hoá nên không chạy Docker local: Postgres, build image và smoke test chỉ kiểm chứng được trên CI.

## 1. Hiện trạng

### Đã xong

| Phase | Trạng thái |
| --- | --- |
| 0 — Secret, repo rác | Đã commit (`a28270f`). **Phần An làm tay (thu hồi Gmail app password) chưa đánh dấu xong trong TODO_AN.** |
| 1 — Docker/Nginx/scripts | Đã commit (`5e75d79`). Chưa chạy kiểm chứng bằng Docker thật (lúc đó Docker tắt). |
| 2 — Bug + bảo mật | Đã commit (`b3fe990`, `c2b06c6`, `edd5171`). S1 chọn COD. |
| 3 — Test + CI/CD | **Code xong nhưng chưa commit.** CI chưa từng chạy trên GitHub. Chưa cấu hình secrets/runner. |

### Số đo hôm nay (Windows, Python 3.13, SQLite)

| Kiểm tra | Kết quả |
| --- | --- |
| `pytest --cov` | 107 passed, 2 skipped (test concurrency cần PostgreSQL), coverage **95%** |
| `ruff check .` | sạch |
| `makemigrations --check` | sạch |
| `pip install -r requirements.txt` | **Lỗi**: `psycopg2-binary==2.9.9` không có wheel cho Python 3.13, phải build từ source |
| `pip-audit` | **5/9 package có lỗ hổng đã công bố** (bảng dưới). Job `security` của CI sẽ đỏ ngay lần chạy đầu |

| Package | Đang dùng | Advisory | Bản vá tối thiểu | Ghi chú |
| --- | --- | --- | --- | --- |
| django | 5.2.7 | 10 (PYSEC-2025-104…109, PYSEC-2026-197…201, 2090) | 5.2.16 | lên 5.2.17, vẫn LTS |
| pillow | 11.3.0 | 15+ | 12.3.0 | |
| gunicorn | 21.2.0 | 2 (PYSEC-2026-1433/1434) | 22.0.0 | lên 26.x |
| requests | 2.32.5 | PYSEC-2026-2275 | 2.33.0 | **không dùng ở đâu** → bỏ |
| python-dotenv | 1.0.0 | PYSEC-2026-2270 | 1.2.2 | **không dùng ở đâu** → bỏ |

Đã thử trong venv tạm: Django 5.2.17 + Pillow 12.3.0 + gunicorn 26.2.0 + psycopg 3.3.6, bỏ requests/dotenv → **107 passed**, `check --deploy` không có cảnh báo nào do code. Nghĩa là Phase 4 có rủi ro thấp về code; rủi ro chính nằm ở dữ liệu (PostgreSQL 15 → 17).

### Lệch phiên bản giữa các môi trường

| Thành phần | Local | CI | Docker/VM |
| --- | --- | --- | --- |
| Python | 3.13 | 3.11 | 3.11 (`python:3.11-slim`) |
| PostgreSQL | SQLite | 17 | 15 (`postgres:15-alpine`) |
| Nginx | — | 1.25 | 1.25 (nhánh này đã hết hỗ trợ) |

Test chạy trên Postgres 17 nhưng production chạy Postgres 15: thứ được kiểm chứng khác thứ được deploy. Phase 4 phải đưa cả ba về cùng một phiên bản.

### Bug còn sót (đã xác nhận lại trong code hôm nay)

| # | Chỗ lỗi | Hậu quả | Mức |
| --- | --- | --- | --- |
| R1 | `orders.views.payments` dùng `order.order_total` tính lúc `place_order`, nhưng tạo `OrderProduct` từ giỏ hàng **hiện tại** | Thêm hàng vào giỏ sau khi bấm Place Order rồi mới xác nhận → đơn ghi tổng tiền cũ cho nhiều hàng hơn | Cao (sai tiền) |
| R2 | `accounts.views.register`: `username = email.split("@")[0]` | `a@x.com` rồi `a@y.com` → `IntegrityError` → 500 | Cao |
| R3 | `submit_review` không kiểm tra đã mua; `rating` là `FloatField` không giới hạn | Ai cũng review được sản phẩm chưa mua, rating 999 hoặc -5 | Trung bình |
| R4 | `change_password` thiếu `update_session_auth_hash` | Đổi mật khẩu xong bị đăng xuất | Trung bình |
| R5 | `login`, `change_password` dùng `request.POST['...']` | POST thiếu field → `KeyError` → 500 | Trung bình |
| R6 | `login` gộp giỏ khách vào giỏ user: nhánh `else` gán **toàn bộ** giỏ khách cho user bên trong vòng lặp; nhánh `if` chỉ `+1` và bỏ lại dòng của khách | Số lượng sai sau khi đăng nhập | Trung bình |
| R7 | `carts.views._cart_id`: `request.session.create()` trả `None` | Request đầu tiên của khách mới có cart id rỗng | Thấp |
| R8 | `store.views.store`: lọc theo category dùng `Paginator(products, 1)` | Mỗi trang chỉ 1 sản phẩm | Thấp |
| R9 | `store.views.product_detail`: `in_cart` chỉ xét giỏ khách | User đã đăng nhập luôn thấy "chưa có trong giỏ" | Thấp |
| R10 | `store.views.search` không lọc `is_available=True` | Tìm ra sản phẩm đã ẩn | Thấp |
| R11 | `register` gán ảnh `default/default-user.png`, file thật là `default-profile.png` | Ảnh đại diện hỏng | Thấp |

### Việc khác chưa có

- Không có `.github/dependabot.yml`, dù `docs/CI_CD.md` nói Dependabot cập nhật actions.
- Ảnh sản phẩm (`media/`) đã ra khỏi git và không có dữ liệu mẫu. Deploy mới thì cửa hàng trống, người xem portfolio không thấy gì.
- `templates/base.html` vẫn load PayPal SDK (client-id hardcode) dù thanh toán đã chuyển sang COD.
- README chỉ có 2 dòng.
- Không HTTPS, không giới hạn số lần đăng nhập sai, backup chỉ chạy tay.

## 2. Phương án

**Nâng cấp tại chỗ, không viết lại.** App đã có 107 test và CI. Viết lại sẽ bỏ phí phần đó, mà portfolio DevOps cần thấy quy trình (test → scan → deploy → rollback) hơn là framework mới.

Nguyên tắc chọn thứ tự:

1. **Chốt Phase 3 trước.** Nó đang nằm ngoài git; mất máy là mất.
2. **Phase 4 (dependencies) đi trước bug còn sót.** CI có gate `pip-audit`, nên chừng nào còn CVE thì không PR nào xanh được. Sửa bug trên nền phụ thuộc cũ rồi nâng sau thì phải test lại hai lần.
3. **Phase 4B (bug còn sót) trước UI.** R1 và R2 là lỗi tiền và lỗi 500; UI chỉ là bề ngoài.
4. **Phase 7 là tuỳ chọn và có time-box.** Chọn 2–3 mục, không làm hết.

Giữ nguyên các quyết định đã có: Django 5.2 LTS (hỗ trợ bảo mật đến 04/2028), không nâng 6.x; COD cho thanh toán; Bootstrap 5.3 cho UI.

### Quyết định cần An chọn

| # | Câu hỏi | Khuyến nghị | Lý do |
| --- | --- | --- | --- |
| D1 | Python 3.13 hay 3.14? | ~~3.13~~ → **An chọn 3.14** | Mọi package trong lockfile đều có wheel cho 3.14, đã chạy đủ test |
| D2 | Khoá phiên bản bằng `pip-tools` hay `uv`? | **`uv pip compile`** | Ra file `requirements.txt` cùng định dạng (Dockerfile, CI không phải đổi), có `--generate-hashes`, nhanh. `uv` cũng là công cụ hay gặp khi phỏng vấn |
| D3 | VM có dữ liệu Postgres 15 cần giữ không? | — | Có: dump/restore theo runbook ở Phase 4. Không: xoá volume, tạo lại |
| D4 | Có domain để bật HTTPS không? | — | Không có domain thì bỏ mục 7.1 |
| D5 | Phase 7 chọn mục nào? | **7.1 HTTPS, 7.3 backup tự động, 7.4 monitoring** | Ba mục dễ kể thành câu chuyện khi phỏng vấn, mỗi mục ≤ 2 buổi |
| D6 | (Từ Phase 0, còn treo) Dọn lịch sử git bằng `git filter-repo`? | Thu hồi password là đủ nếu đã thu hồi | Password đã thu hồi thì bản trong lịch sử vô dụng. Viết lại lịch sử chỉ cần khi không thu hồi được |

## 3. Kế hoạch theo phase

| Phase | Nội dung | Ước lượng |
| --- | --- | --- |
| 3.9 | Chốt Phase 3: commit, cấu hình GitHub | 0.5 buổi |
| 4 | Dependencies + đồng bộ runtime | 1–2 buổi |
| 4B | Bug còn sót R1–R11 | 2 buổi |
| 5 | UI Bootstrap 5.3 (time-box) | 2–5 buổi |
| 6 | Dữ liệu mẫu, README, incidents | 1–2 buổi |
| 7 | DevOps nâng cao (chọn 2–3 mục) | 2–6 buổi |

### Phase 3.9 — Chốt Phase 3

- [ ] An đọc lại diff Phase 3 (`git diff`, các file `??` trong `git status`), rồi đồng ý commit.
- [ ] Làm từ đây trở đi trên nhánh (ví dụ `upgrade/phase-4`) và mở PR vào `main`. CI chạy trên PR gồm lint/test/security/build nhưng **không push image, không deploy**, nên an toàn để thử.
- [ ] Làm các mục "Từ Phase 3" trong TODO_AN (secrets Docker Hub, `DEPLOY_DIR`, environment `production`, self-hosted runner, branch protection). Riêng runner và secrets có thể để sau Phase 4.
- Kiểm chứng: PR đầu tiên có `lint` và `test` xanh. `security` đỏ là **đúng dự kiến** (CVE ở bảng trên), Phase 4 sẽ làm nó xanh.

### Phase 4 — Dependencies và runtime

**4.1 Python packages**

| Package | Hiện tại | Lên | Ghi chú |
| --- | --- | --- | --- |
| django | 5.2.7 | 5.2.17 | patch release trong LTS, không đổi API |
| pillow | 11.3.0 | 12.3.0 | |
| gunicorn | 21.2.0 | 26.2.0 | các flag trong Dockerfile vẫn dùng được |
| psycopg2-binary | 2.9.9 | `psycopg[binary]` 3.3.x | `DB_ENGINE` giữ nguyên `django.db.backends.postgresql`; Django tự nhận psycopg 3 |
| requests | 2.32.5 | **bỏ** | không có dòng `import requests` nào |
| python-dotenv | 1.0.0 | **bỏ** | settings dùng `python-decouple` |
| django-session-timeout | 0.1.0 | **bỏ** (đề xuất) | package không còn được phát triển. Thay bằng có sẵn trong Django: `SESSION_COOKIE_AGE = 3600` + `SESSION_SAVE_EVERY_REQUEST = True`. Cần test: phiên hết hạn sau 1 giờ không hoạt động |
| django-admin-thumbnails | 0.2.9 | giữ | chỉ dùng trong admin |
| python-decouple | 3.8 | giữ | đã là bản mới nhất |

- [x] Tạo `requirements.in` (tên package + ràng buộc như `django>=5.2,<5.3`) và `requirements-dev.in`. Sinh `requirements.txt` có hash bằng `uv pip compile` (theo D2). Dockerfile cài bằng `pip install --require-hashes`.
- [x] `requirements-dev.txt` hiện không ghim phiên bản (`pytest`, `ruff`...). Ghim luôn, để CI hôm nay và CI tháng sau chạy cùng một ruff.

**4.2 Đồng bộ runtime**

- [x] `Dockerfile`: `python:3.11-slim` → `python:3.14-slim`.
- [x] `ci.yml`: `PYTHON_VERSION: "3.14"`. `ruff.toml`: `target-version = "py314"`.
- [x] `docker-compose.yml` và `docker-compose.prod.yml`: `postgres:15-alpine` → `postgres:17-alpine`, trùng với service test của CI.
- [x] `docker-compose.prod.yml`: `nginx:1.25-alpine` → `nginx:1.30-alpine` (stable hiện hành).
- [x] `.dockerignore`: thêm `**/tests.py`, `**/test_*.py`, `conftest.py`, `pytest.ini`, `.coveragerc`, để image production không chứa test.

**4.3 Runbook nâng PostgreSQL 15 → 17 trên VM** (chỉ khi D3 = có dữ liệu)

Volume dữ liệu của Postgres 15 không mở được bằng Postgres 17, nên phải dump/restore:

1. `backups/backup.sh` (dump bằng Postgres 15 đang chạy). Mở file `.sql.gz` ra xem có dữ liệu thật.
2. `docker compose --env-file .env.prod -f docker-compose.prod.yml down`
3. Xoá **chỉ** volume Postgres: `docker volume rm koffeecart_postgres_data`.
4. Deploy image/compose mới (Postgres 17), chờ `db` healthy.
5. `backups/backup.sh restore` file vừa dump. Kiểm tra số đơn hàng và số user khớp với trước khi nâng.

Đánh đổi: có downtime vài phút. Với dự án portfolio thì chấp nhận được; `pg_upgrade` tránh được downtime nhưng phức tạp hơn nhiều so với lợi ích.

**4.4 Tự động cập nhật**

- [x] Thêm `.github/dependabot.yml` cho 3 hệ: `pip`, `docker` (base image), `github-actions`. Lịch hàng tuần, gom nhóm patch để không bị spam PR.

Kiểm chứng Phase 4:

```bash
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
pytest -q
pip-audit -r requirements.txt --require-hashes --disable-pip   # "No known vulnerabilities found"
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build --wait
docker exec koffeecart_web python --version   # 3.14.x
docker exec koffeecart_db postgres --version  # 17.x
```

Và PR trên GitHub có cả 4 job `lint`, `test`, `security`, `build` xanh.

### Phase 4B — Bug còn sót

Cùng quy tắc với Phase 2: mỗi bug một regression test, test fail trước khi sửa, pass sau khi sửa.

| # | Cách sửa | Test |
| --- | --- | --- |
| R1 | Trong `payments`, tính lại tổng từ giỏ đã khoá (`calculate_totals`), so với `order.order_total`. Lệch thì không đặt đơn, báo user quay lại checkout | đặt đơn → thêm hàng → xác nhận → đơn không được đặt, kho không đổi |
| R2 | Sinh username không trùng (phần trước `@` + hậu tố ngắn khi đã tồn tại). Không đổi model | đăng ký `a@x.com` rồi `a@y.com` → cả hai thành công |
| R3 | `submit_review` chỉ nhận khi user có `OrderProduct` của sản phẩm đó. `rating`: validator 1–5 (cần migration) | chưa mua → bị từ chối; `rating=9` → form invalid |
| R4 | `update_session_auth_hash(request, user)` sau `set_password` | đổi mật khẩu xong vẫn vào được dashboard |
| R5 | `request.POST.get(..., '')` | POST rỗng tới login → không 500 |
| R6 | Viết lại phần gộp giỏ: với mỗi dòng của khách, có dòng cùng sản phẩm + biến thể thì cộng `quantity`, không thì chuyển dòng sang user. Bọc trong `transaction.atomic()` | giỏ khách 2×A, giỏ user 1×A → sau login 3×A, không còn dòng mồ côi |
| R7 | Sau `request.session.create()` đọc lại `request.session.session_key` | client mới thêm hàng ngay request đầu → giỏ có 1 dòng |
| R8 | Dùng chung một hằng số page size (ví dụ 6) cho cả hai nhánh | category có 3 sản phẩm → 1 trang hiển thị cả 3 |
| R9 | Dùng `_cart_items(request)` (đã xét user/khách) thay cho lọc theo `cart_id` | user đã đăng nhập, có A trong giỏ → `in_cart` là True |
| R10 | Thêm `is_available=True` vào `search` | sản phẩm ẩn không xuất hiện trong kết quả |
| R11 | Sửa đường dẫn thành `default/default-profile.png` | profile mới có ảnh tồn tại trên đĩa |

Thứ tự: R1, R2 trước (sai tiền, lỗi 500), sau đó R5, R4, R6, R3, rồi nhóm thấp.

Có thay đổi model (R3) nên chạy `makemigrations` rồi `makemigrations --check`.

### Phase 5 — UI (giữ như FIX_PLAN, thêm vài mục)

Giữ toàn bộ phần Phase 5 trong FIX_PLAN (Bootstrap 5.3, bỏ jQuery, đổi class BS4 → BS5, CSS variables tông cà phê, trang 404/500 riêng). Thêm:

- [ ] Xoá hẳn thẻ PayPal SDK khỏi `base.html` (thanh toán đã là COD, không còn trang nào cần).
- [ ] `cart.html` hiển thị tổng tiền, thuế, tổng cộng (view đã truyền sẵn).
- [ ] Sau khi bỏ hết inline script: thêm header `Content-Security-Policy` ở Nginx. Làm sau cùng vì CSP sẽ chặn mọi inline script còn sót.
- [ ] Smoke test trong CI hiện kiểm tra `/static/css/ui.css`. Đổi tên/xoá file CSS thì sửa dòng đó trong `ci.yml`.

Time-box: hết 5 buổi thì dừng, phần còn lại ghi vào backlog.

### Phase 6 — Dữ liệu mẫu và tài liệu

- [ ] Management command `python manage.py seed_demo`: tạo category, vài sản phẩm, ảnh mẫu nhỏ (commit trong `store/fixtures/` hoặc tương tự, không dùng `media/`). Chạy lại nhiều lần không tạo trùng. Giải quyết luôn mục "ảnh sản phẩm" còn treo trong TODO_AN.
- [ ] README tiếng Anh như FIX_PLAN Phase 6: kiến trúc (sơ đồ Nginx → Gunicorn → Postgres), cách chạy, biến môi trường, backup/restore, CI/CD (link `docs/CI_CD.md`), số liệu đo được (số test, coverage, thời gian pipeline, kích thước image). Ghi rõ app gốc từ khoá học GreatKart.
- [ ] `docs/incidents.md`: mỗi lỗi lớn đã sửa (S1, S2, B6, static 404 ở Phase 1, R1) theo format triệu chứng → nguyên nhân gốc → cách sửa → test.

### Phase 7 — DevOps nâng cao (tuỳ chọn, chọn 2–3 mục)

| # | Mục | Việc chính | Học được gì / kể gì khi phỏng vấn | Ước lượng |
| --- | --- | --- | --- | --- |
| 7.1 | HTTPS | Domain trỏ về server; Certbot (hoặc thay Nginx bằng Caddy, tự lấy cert). Bật các biến `SECURE_*` đã có sẵn trong `.env.prod` | TLS termination, HSTS, vì sao cookie `Secure` phá login trên HTTP | 1 buổi |
| 7.2 | Chống dò mật khẩu | `limit_req` của Nginx cho `/accounts/login/` và `/accounts/forgotPassword/` | Rate limiting ở tầng proxy, không phải sửa app | 0.5 buổi |
| 7.3 | Backup tự động | systemd timer (hoặc cron) chạy `backup.sh` hằng đêm; đẩy bản sao ra ngoài VM (object storage hoặc máy khác); **diễn tập restore** định kỳ và ghi lại thời gian | "Backup chưa restore thử thì chưa phải backup"; RPO/RTO | 1–2 buổi |
| 7.4 | Monitoring | Mức nhẹ: Uptime Kuma theo dõi `/health/`, báo qua Telegram/email. Mức đầy đủ: Prometheus + Grafana + `django-prometheus` + cAdvisor | Metrics vs logs, alert khi nào thì đáng gửi | 1–3 buổi |
| 7.5 | Provision bằng code | Thay đoạn shell trong `Vagrantfile` bằng Ansible playbook (cài Docker, tạo user, cài runner). Lên cloud thì thêm Terraform | Infrastructure as Code, chạy lại nhiều lần ra cùng kết quả | 2 buổi |
| 7.6 | Staging | Thêm environment `staging` trong GitHub; PR deploy lên staging, merge mới lên production | Môi trường trung gian, promotion cùng một image | 1–2 buổi |

Khuyến nghị (D5): 7.1 + 7.3 + 7.4 mức nhẹ. Nếu không có domain thì thay 7.1 bằng 7.2.

## 4. Rủi ro

| Rủi ro | Giảm thiểu |
| --- | --- |
| Mất dữ liệu khi nâng Postgres 15 → 17 | Runbook 4.3: dump, mở file kiểm tra, rồi mới xoá volume. Đếm bản ghi trước/sau |
| Migration tiền (B8, Phase 2) chưa từng chạy trên PostgreSQL | Chạy `migrate` trên bản copy dữ liệu thật (restore vào Postgres 17 local) trước khi deploy |
| CI đỏ lần đầu vì cấu hình GitHub thiếu | Làm trên PR trước; job `deploy` chỉ chạy khi push `main` |
| Phase 5 kéo dài | Time-box 5 buổi |
| Phase 7 lan man | Chỉ chọn 2–3 mục, mỗi mục có tiêu chí "xong" rõ ràng trước khi bắt đầu |
