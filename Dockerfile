# Base image
FROM python:3.11-slim

# Không tạo file .pyc
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Thư mục làm việc trong container
WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev\
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Sao chép file requirements và cài đặt
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn
COPY . /app/

RUN python manage.py collectstatic --noinput || true

# Mở cổng cho Django dev server
EXPOSE 8000

# Lệnh khởi động
CMD ["gunicorn", "koffeecart.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]

