"""Expose only Sentinel's webhook during local GitHub integration tests.

Run this loopback-only gateway behind a temporary HTTPS tunnel. It forwards bounded
GitHub notifications to the local API; the UI, database and authenticated API stay
unreachable through the tunnel. This development helper is not a production proxy.
"""

from __future__ import annotations

import argparse
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, Response

WEBHOOK_PATH = "/api/github/webhook"
MAX_BODY_BYTES = 1_048_576
FORWARDED_HEADERS = ("content-type", "x-github-event", "x-github-delivery", "x-hub-signature-256")


def create_gateway(target: str, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Forward the exact webhook path to a loopback API, with no general proxy route."""
    url = urlsplit(target)
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.username is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("the target must be a plain HTTP loopback address")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request) -> Response:
        if request.headers.get("transfer-encoding"):
            return Response(status_code=400)
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return Response(status_code=411)
        if int(length) > MAX_BODY_BYTES:
            return Response(status_code=413)
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BODY_BYTES:
                return Response(status_code=413)
        headers = {key: request.headers[key] for key in FORWARDED_HEADERS if key in request.headers}
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=15, trust_env=False
            ) as client:
                result = await client.post(
                    target.rstrip("/") + WEBHOOK_PATH, content=bytes(body), headers=headers
                )
        except httpx.HTTPError:
            return Response(status_code=502)
        return Response(
            result.content, status_code=result.status_code, media_type="application/json"
        )

    return app


def main() -> None:
    """Start the local gateway; the tunnel points to this port instead of the full API."""
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    options = parser.parse_args()
    uvicorn.run(
        create_gateway(options.target), host="127.0.0.1", port=options.port, access_log=False
    )


if __name__ == "__main__":
    main()
