# Base image
FROM python:3.11-slim

# Không tạo file .pyc
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Thư mục làm việc trong container
WORKDIR /app

# Sao chép file requirements và cài đặt
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn
COPY . /app/

# Mở cổng cho Django dev server
EXPOSE 8000

# Lệnh khởi động
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
