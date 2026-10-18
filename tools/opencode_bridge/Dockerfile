FROM node:22-bookworm-slim AS download
RUN npm install --global --omit=dev --no-audit --no-fund opencode-ai@1.19.3 \
    && cp /usr/local/lib/node_modules/opencode-ai/node_modules/opencode-linux-$(node -p process.arch)/bin/opencode /opencode

FROM python:3.14-slim-bookworm
COPY --from=download /opencode /usr/local/bin/opencode
RUN opencode --version
COPY __init__.py runner.py server.py opencode.json /app/opencode_bridge/
ENV XDG_CONFIG_HOME=/tmp/config \
    XDG_DATA_HOME=/tmp/data \
    XDG_CACHE_HOME=/tmp/cache \
    XDG_STATE_HOME=/tmp/state \
    OPENCODE_CONFIG=/app/opencode_bridge/opencode.json \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    OPENCODE_DISABLE_DEFAULT_PLUGINS=true \
    OPENCODE_DISABLE_LSP_DOWNLOAD=true \
    OPENCODE_DISABLE_AUTOCOMPACT=true \
    OPENCODE_DISABLE_CLAUDE_CODE=true \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER 10001:10001
EXPOSE 4097
ENTRYPOINT ["python", "-m", "opencode_bridge.server"]
