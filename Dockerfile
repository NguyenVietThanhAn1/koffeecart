# ---- Stage 1: build the virtualenv ----
FROM python:3.11-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: runtime (no compilers, no root) ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . /app
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

CMD ["gunicorn", "koffeecart.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
