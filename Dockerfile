# Sentinel API + worker image.
#
#   docker build -t sentinel .
#   docker compose up            # API on http://127.0.0.1:8000, worker, PostgreSQL
#
# The image runs as an unprivileged user. It does NOT contain the fix sandbox: fixes are
# tested in separate, locked-down containers built from Dockerfile.sandbox.

# --- 1. Web UI: bundle the React app into the Python package's static folder ----------
FROM node:22-slim AS web
WORKDIR /build/web
COPY web/package.json ./
RUN npm install --no-audit --no-fund
COPY web/ ./
# build.mjs writes to ../src/sentinel/apps/api/static (here: /build/src/...)
RUN npm run build

# --- 2. Python application ------------------------------------------------------------
FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SENTINEL_LOG_FORMAT=json \
    SENTINEL_CACHE_DIR=/home/sentinel/.cache/sentinel
# git: reading local repositories; node + typescript: full TS/JS structure extraction.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm \
 && npm install -g typescript@5 \
 && rm -rf /var/lib/apt/lists/* /root/.npm
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY --from=web /build/src/sentinel/apps/api/static/ src/sentinel/apps/api/static/
RUN pip install ".[postgres,analyzers]"
RUN useradd --create-home --uid 10001 sentinel
USER sentinel
EXPOSE 8000
# Token auth is required to listen on a non-loopback address (see `sentinel serve`).
ENV SENTINEL_AUTH_MODE=token
CMD ["sentinel", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-worker"]
