# Việc An cần tự làm

- [ ] **Thu hồi Gmail app password cũ** (Google Account → Security → App passwords). Nó vẫn nằm trong lịch sử git (commit `9ba572c` trở về trước). Repo public nên coi như đã lộ. Làm ngay.
- [ ] Quyết định có dọn lịch sử git bằng `git filter-repo` không. Phải force-push và viết lại lịch sử. Claude không chạy khi chưa được đồng ý.
- [ ] Backup `db.sqlite3` cũ nếu còn dữ liệu cần giữ. File đã ra khỏi git nhưng vẫn nằm trên đĩa.
- [ ] Tạo `.env` thật từ `.env.example`: `SECRET_KEY`, DB, email. Không commit file này.
- [ ] Chọn hướng cho lỗi S1 (thanh toán): xác minh PayPal phía server, hay mock/COD. Cần trước Phase 2.
- [x] Ảnh sản phẩm trong `media/` đã ra khỏi git. Phase 6: `python manage.py seed_demo` tạo sản phẩm mẫu và tự vẽ ảnh, nên server mới không cần chép ảnh. Ảnh thật upload qua admin nằm trong volume `media_volume`.
- [ ] (Tuỳ chọn) Chạy `git add --renormalize .` để chuẩn hoá CRLF cũ, khi muốn.

## Từ Phase 1
- [ ] Bật Docker Desktop rồi tự chạy kiểm chứng Phase 1 (Claude không build được vì daemon tắt). Lệnh ở cuối báo cáo Phase 1.
- [ ] Tạo `.env.prod` thật (không commit): `SECRET_KEY`, `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT=5432`, `ALLOWED_HOSTS` (phải có `localhost`), `CSRF_TRUSTED_ORIGINS`, `EMAIL_*`.
- [ ] Nếu VM đã có volume `static_volume` cũ (chủ sở hữu root): chạy `docker compose --env-file .env.prod -f docker-compose.prod.yml down -v` một lần. Lưu ý `-v` xoá luôn volume Postgres, nên backup trước bằng `backups/backup.sh`.
- [ ] Nếu đã chạy dưới tên project cũ, xoá container cũ (`koffeecart_web`...) trước khi `up`, vì tên project compose vừa đổi.
- [ ] Trước khi CI push image (Phase 3), deploy bằng `./deploy.sh --build` trên VM.
- [ ] `monitor.sh` còn dùng `docker-compose.prod.yml` không kèm `--env-file`. Kiểm tra lại khi chạy trên VM.

## Từ Phase 2
- [ ] **Backup DB trước khi deploy migration tiền (B8)**: chạy `backups/backup.sh`. Migration `store/0006` và `orders/0003` đổi `price`, `order_total`, `tax`, `product_price` sang `DecimalField(10,2)` và `amount_paid` từ chuỗi sang số. Đã thử trên SQLite với dữ liệu cũ; chưa thử trên PostgreSQL (Docker tắt).
- [ ] Đơn COD có trạng thái thanh toán `Pending`. Sau khi giao hàng, đổi trạng thái đơn/thanh toán trong admin (`/securelogin/`). Chưa có luồng tự động.
- [ ] Chạy `pytest -q` và `ruff check .` để tự kiểm chứng (cần `pip install -r requirements.txt -r requirements-dev.txt`).

### Phát hiện thêm trong Phase 2 (ngoài plan)
Đã sửa hết ở Phase 4B (R1–R11 trong `docs/UPGRADE_PLAN.md`), riêng cart.html/PayPal SDK sửa ở Phase 5.
- `register`: `username = email.split("@")[0]`, nên `a@x.com` và `a@y.com` trùng username, gây lỗi 500 khi đăng ký người thứ hai.
- `submit_review`: user đăng nhập nào cũng gửi được review cho sản phẩm chưa mua (template chỉ ẩn form). `rating` không giới hạn 1–5.
- `change_password`: đổi xong thì session bị vô hiệu (thiếu `update_session_auth_hash`), user bị đăng xuất.
- `carts.views._cart_id`: `request.session.create()` trả `None`, nên request đầu tiên của khách mới nhận cart id rỗng (chạy được nhờ request sau).
- `store.views.store`: lọc theo category chỉ hiện 1 sản phẩm/trang (`Paginator(products, 1)`), có vẻ là giá trị debug.
- `register` gán ảnh mặc định `default/default-user.png` nhưng thư mục `media/default` chỉ có `default-profile.png`, nên ảnh đại diện hỏng.
- `cart.html` không hiển thị tổng tiền và `base.html` vẫn load PayPal SDK ở mọi trang. Để Phase 5.

## Từ Phase 3 (CI/CD)
Chi tiết từng bước ở [docs/CI_CD.md](CI_CD.md).
- [ ] GitHub → Settings → Secrets → Actions: thêm `DOCKERHUB_USERNAME` và `DOCKERHUB_TOKEN` (access token, không dùng mật khẩu). Tên image giờ tự lấy từ `DOCKERHUB_USERNAME`, không còn hardcode `annguyn0810`.
- [ ] Thêm repository variable `DEPLOY_DIR` (đường dẫn thư mục clone trên VM, có `.env.prod`) và environment `production` (nên bật required reviewers).
- [ ] Cài self-hosted runner trên VM với label `koffeecart`. Runner user phải chạy được `docker`. Nếu repo Docker Hub private thì `docker login` một lần trên VM.
- [ ] Bật branch protection cho `main`: bắt buộc các check `lint`, `test`, `security`, `build`.
- [ ] Lần chạy CI đầu tiên có thể đỏ ở `pip-audit`/Trivy nếu còn phụ thuộc cũ. Phase 4 đã nâng phụ thuộc lên bản vá.

## Từ Phase 4
- [ ] PostgreSQL đổi từ 15 sang 17. Volume cũ của Postgres 15 không mở được bằng 17. VM không có dữ liệu cần giữ, nên trước lần deploy đầu tiên chạy: `docker compose --env-file .env.prod -f docker-compose.prod.yml down -v` (xoá cả volume), rồi `up` lại.
- [ ] Máy local cần Python 3.14 (`uv python install 3.14`) và cài phụ thuộc bằng `pip install --require-hashes -r requirements.txt -r requirements-dev.txt`.
- [ ] Docker build, test trên PostgreSQL và smoke test chưa chạy được ở local (tắt ảo hoá). Kiểm chứng bằng CI trên PR.


## Từ Phase 6
- [ ] `db.sqlite3` local đã được migrate lên schema mới và nạp dữ liệu mẫu (giữ nguyên 6 sản phẩm, 5 đơn cũ). Bản gốc trước khi nâng cấp: `db-backup-2026-10-06-before-upgrade.sqlite3` (git bỏ qua). Xoá khi không cần nữa.
- [ ] Sau lần deploy đầu lên Linux: `docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py seed_demo` rồi `... exec web python manage.py createsuperuser`.

## Từ Phase 7
- [ ] Deploy lên Linux theo `docs/DEPLOY_LINUX.md` (Docker, ufw, `.env.prod`, `./deploy.sh --build`, `seed_demo`, `createsuperuser`).
- [ ] Thêm `WEB_IMAGE=<dockerhub-user>/koffeecart` vào `.env.prod` trên server, để `./deploy.sh <tag>` và `--rollback` chạy tay vẫn kéo đúng image.
- [ ] `sudo deploy/systemd/install.sh` để bật backup hằng đêm + restore drill hằng tuần; chạy thử một lần rồi xem `logs/backup.log`.
- [ ] (Nên làm) Cấu hình rclone và `BACKUP_OFFSITE`, để có bản backup nằm ngoài server.
- [ ] (Tuỳ chọn) Bật Uptime Kuma (`--profile monitoring`) và cài thông báo Telegram/email.
- [ ] Khi có domain: làm 7.1 (HTTPS) rồi bật các biến `SECURE_*` (xem `docs/CI_CD.md`).
