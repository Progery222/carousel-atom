# syntax=docker/dockerfile:1.7
# Multi-stage build: Node compiles the frontend, Python runs FastAPI
# that serves both the API and the prebuilt static assets.

# ── Stage 1: build the frontend ─────────────────────────────────────────────
FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

# Pillow needs libjpeg/zlib/freetype headers to *use* the matching libs at
# runtime. We also keep curl for the container-side healthcheck script.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        libpng16-16 \
        libwebp7 \
        libfreetype6 \
        libopenjp2-7 \
        zlib1g \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=5 \
    PIP_TIMEOUT=60

# Install Python deps first so the layer is cacheable.
# The base image ships a working pip; we deliberately don't `pip install
# --upgrade pip` because that fetches the PyPI JSON index and we've seen
# it return truncated responses ("Unterminated string at column 732101")
# that fail the whole build for a transient network/CDN issue.
COPY backend/pyproject.toml /app/backend/pyproject.toml
RUN pip install \
        "pillow>=10.0" \
        "requests>=2.31" \
        "beautifulsoup4>=4.12" \
        "feedparser>=6.0" \
        "pyyaml>=6.0" \
        "pytz>=2024.1" \
        "python-dotenv>=1.0" \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.29" \
        "python-multipart>=0.0.9" \
        "slowapi>=0.1.9"

# Copy backend source (after deps so source edits don't bust the deps layer).
COPY backend/ /app/backend/

# Copy the built frontend out of Stage 1.
COPY --from=frontend /build/dist /app/frontend/dist

# Railway mounts a volume at this path for persistent SQLite + rendered runs.
RUN mkdir -p /app/backend/data

# Run as root. We previously had a `carousel` non-root user, but Railway
# mounts its persistent volume on /app/backend/data AFTER the Dockerfile
# chown runs, so the mount point comes back owned by root:root and a
# non-root process can't create /app/backend/data/output at startup
# (PermissionError on import of api.server). Switching to root is the
# cleanest fix — the container is locked behind Railway's gateway and
# the app doesn't exec untrusted shell input.

WORKDIR /app/backend
EXPOSE 8000

# Railway sets $PORT. Locally `docker run` defaults to 8000.
ENV PORT=8000
CMD ["sh", "-c", "exec python -m uvicorn api.server:app --host 0.0.0.0 --port ${PORT}"]
