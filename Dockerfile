# Multi-stage Dockerfile for Cloud Run deployment.
# Stage 1 installs dependencies; stage 2 copies only what Cloud Run needs.
# $PORT is injected by Cloud Run at runtime; gunicorn.conf.py reads it.

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --target /build/deps

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/deps" \
    PATH="/app/deps/bin:$PATH"

WORKDIR /app

# System deps needed at runtime (psycopg binary, docx, pdf)
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /build/deps /app/deps

# Copy application code (excludes dev dirs via .dockerignore)
COPY app.py gunicorn.conf.py ./
COPY scripts/ ./scripts/
COPY templates/ ./templates/
COPY static/ ./static/
COPY prompts/ ./prompts/

# Cloud Run injects $PORT; default 8080 matches Cloud Run convention
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8080}/health')" || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
