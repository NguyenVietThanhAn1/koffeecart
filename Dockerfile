# ---- Stage 1: build the virtualenv ----
FROM python:3.14-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
# requirements.txt is a lock file with a sha256 per package: pip refuses anything that
# does not match, so a tampered or swapped package cannot get into the image.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# ---- Stage 2: runtime (no compilers, no root) ----
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    WEB_CONCURRENCY=3

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# The code belongs to root and is read-only for the app user: a compromised app process
# cannot change it. Only collected static files and uploads are writable.
COPY . /app
RUN mkdir -p /app/staticfiles /app/media \
    && chown app:app /app/staticfiles /app/media

USER app

# A failing collectstatic must fail the build, so there is no "|| true".
# SECRET_KEY is a throwaway value used only at build time.
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000

# Host is "localhost", so keep localhost in ALLOWED_HOSTS.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/', timeout=3)" || exit 1

# Workers come from WEB_CONCURRENCY (gunicorn reads it), so a server can change it in
# .env.prod without a rebuild. /dev/shm keeps the worker heartbeat files off the container disk.
CMD ["gunicorn", "koffeecart.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--worker-tmp-dir", "/dev/shm", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
