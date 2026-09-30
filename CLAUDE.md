# KoffeeCart — hướng dẫn cho Claude Code

Django e-commerce (Nginx → Gunicorn → PostgreSQL, Docker Compose, GitHub Actions). Đây là dự án portfolio DevOps của An. An đang học, nên mọi thay đổi phải giải thích được.

## Kế hoạch

Đọc `docs/FIX_PLAN.md` trước khi làm bất cứ việc gì. Làm đúng thứ tự Phase 0 → 6.

## Quy tắc làm việc

- Mỗi lần chỉ làm **một phase**, hoặc một nhóm nhỏ trong phase. Làm xong thì DỪNG và báo lại:
  - đã sửa gì, file nào;
  - vì sao sửa như vậy, đánh đổi là gì;
  - lệnh để An tự kiểm chứng.
- Không commit, không push, không chạy `git filter-repo` khi An chưa đồng ý.
- Không đưa secret thật vào bất kỳ file nào. Giá trị mẫu chỉ đặt trong `.env.example`.
- Lỗi S1 (thanh toán) phải chờ An chọn: xác minh PayPal phía server, hay dùng mock/COD.
- Mỗi bug ở Phase 2 phải có regression test. Test phải fail trước khi sửa và pass sau khi sửa.
- Có thay đổi model thì chạy `python manage.py makemigrations`, rồi `makemigrations --check`.
- Giữ Django 5.2 LTS, không nâng lên 6.x.

## Lệnh hữu ích

```bash
# chạy local không cần Docker
export SECRET_KEY=dev DEBUG=True ALLOWED_HOSTS=localhost,127.0.0.1
python manage.py migrate && python manage.py runserver

# test và lint
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
ruff check .

# stack production
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```
