# Sentinel API + worker image.
#
#   docker build -t sentinel .
#   docker compose up            # API on http://127.0.0.1:8000, worker, PostgreSQL
#
# The image runs as an unprivileged user. It does NOT contain the fix sandbox: fixes are
# tested in separate, locked-down containers built from Dockerfile.sandbox.

# --- Trusted JS analyzers: one locked dependency tree shared with sandbox and CI -----
FROM node:22-slim AS analyzers
WORKDIR /opt/sentinel-tools
COPY tools/analyzers/package.json tools/analyzers/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM docker:29.8.1-cli AS docker-cli

# --- 1. Web UI: bundle the React app into the Python package's static folder ----------
FROM node:22-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# build.mjs writes to ../src/sentinel/apps/api/static (here: /build/src/...)
RUN npm run build

# --- 2. Python application ------------------------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SENTINEL_LOG_FORMAT=json \
    SENTINEL_CACHE_DIR=/tmp/sentinel-cache \
    NODE_PATH=/opt/sentinel-tools/node_modules \
    PATH=/opt/sentinel-tools/node_modules/.bin:$PATH
# git reads repositories; Node 22 and locked tools match CI and the fix sandbox.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git libstdc++6 libatomic1 \
 && rm -rf /var/lib/apt/lists/* /root/.npm
COPY --from=analyzers /usr/local/bin/node /usr/local/bin/node
COPY --from=analyzers /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=analyzers /opt/sentinel-tools /opt/sentinel-tools
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
WORKDIR /app
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY src/ src/
COPY --from=web /build/src/sentinel/apps/api/static/ src/sentinel/apps/api/static/
RUN pip install -c requirements.lock ".[postgres,analyzers]"
RUN useradd --create-home --uid 10001 sentinel \
 && mkdir /repos && chown sentinel:sentinel /repos
USER sentinel
EXPOSE 8000
# Token auth is required to listen on a non-loopback address (see `sentinel serve`).
ENV SENTINEL_AUTH_MODE=token

# Only the dedicated fix worker has a Docker client. Compose grants this worker alone
# daemon access; generated containers receive neither that socket nor worker secrets.
FROM runtime AS validation-worker
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
CMD ["sentinel", "worker", "--kind", "fix", "--require-sandbox"]

FROM runtime AS app
CMD ["sentinel", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-worker"]
