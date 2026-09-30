# Việc An cần tự làm

- [ ] **Thu hồi Gmail app password cũ** (Google Account → Security → App passwords). Nó vẫn nằm trong lịch sử git (commit `9ba572c` trở về trước). Repo public nên coi như đã lộ. Làm ngay.
- [ ] Quyết định có dọn lịch sử git bằng `git filter-repo` không. Phải force-push và viết lại lịch sử. Claude không chạy khi chưa được đồng ý.
- [ ] Backup `db.sqlite3` cũ nếu còn dữ liệu cần giữ. File đã ra khỏi git nhưng vẫn nằm trên đĩa.
- [ ] Tạo `.env` thật từ `.env.example`: `SECRET_KEY`, DB, email. Không commit file này.
- [ ] Chọn hướng cho lỗi S1 (thanh toán): xác minh PayPal phía server, hay mock/COD. Cần trước Phase 2.
- [ ] Ảnh sản phẩm trong `media/` đã ra khỏi git. Quyết định cách giữ ảnh (volume, seed lại, hoặc object storage).
- [ ] (Tuỳ chọn) Chạy `git add --renormalize .` để chuẩn hoá CRLF cũ, khi muốn.

## Từ Phase 1
- [ ] Bật Docker Desktop rồi tự chạy kiểm chứng Phase 1 (Claude không build được vì daemon tắt). Lệnh ở cuối báo cáo Phase 1.
- [ ] Tạo `.env.prod` thật (không commit): `SECRET_KEY`, `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT=5432`, `ALLOWED_HOSTS` (phải có `localhost`), `CSRF_TRUSTED_ORIGINS`, `EMAIL_*`.
- [ ] Nếu VM đã có volume `static_volume` cũ (chủ sở hữu root): chạy `docker compose --env-file .env.prod -f docker-compose.prod.yml down -v` một lần. Lưu ý `-v` xoá luôn volume Postgres, nên backup trước bằng `backups/backup.sh`.
- [ ] Nếu đã chạy dưới tên project cũ, xoá container cũ (`koffeecart_web`...) trước khi `up`, vì tên project compose vừa đổi.
- [ ] Trước khi CI push image (Phase 3), deploy bằng `./deploy.sh --build` trên VM.
- [ ] `monitor.sh` còn dùng `docker-compose.prod.yml` không kèm `--env-file`. Kiểm tra lại khi chạy trên VM.
