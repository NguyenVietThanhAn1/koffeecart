# Việc An cần tự làm

- [ ] **Thu hồi Gmail app password cũ** (Google Account → Security → App passwords). Nó vẫn nằm trong lịch sử git (commit `9ba572c` trở về trước). Repo public nên coi như đã lộ. Làm ngay.
- [ ] Quyết định có dọn lịch sử git bằng `git filter-repo` không. Phải force-push và viết lại lịch sử. Claude không chạy khi chưa được đồng ý.
- [ ] Backup `db.sqlite3` cũ nếu còn dữ liệu cần giữ. File đã ra khỏi git nhưng vẫn nằm trên đĩa.
- [ ] Tạo `.env` thật từ `.env.example`: `SECRET_KEY`, DB, email. Không commit file này.
- [ ] Chọn hướng cho lỗi S1 (thanh toán): xác minh PayPal phía server, hay mock/COD. Cần trước Phase 2.
- [ ] Ảnh sản phẩm trong `media/` đã ra khỏi git. Quyết định cách giữ ảnh (volume, seed lại, hoặc object storage).
- [ ] (Tuỳ chọn) Chạy `git add --renormalize .` để chuẩn hoá CRLF cũ, khi muốn.
