# Macrolog image. Pure Python dependencies only, so it builds on linux/amd64 and linux/arm64 without compilers.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/data/macrolog.db

WORKDIR /app

# Unprivileged user. /data is owned by it so the named volume is writable.
RUN groupadd --system --gid 10001 macrolog \
 && useradd --system --uid 10001 --gid macrolog --home-dir /nonexistent --shell /usr/sbin/nologin macrolog \
 && mkdir -p /data \
 && chown macrolog:macrolog /data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER macrolog

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/auth/config', timeout=4)"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
