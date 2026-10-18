"""GitHub webhook receiver.

GitHub calls this route when a pull request is opened or updated. The route only
verifies the signature, parses the event and queues a review
(``ReviewService.create_github``); the worker does the actual work and posts comments.
See ``sentinel/integrations/github`` for the client, event parsing and comment rendering.
"""

# No `from __future__ import annotations`: FastAPI evaluates route signatures.

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from sentinel.apps.api.dependencies import ContextDep
from sentinel.integrations.github.webhooks import parse_pull_request_event, verify_signature

router = APIRouter(tags=["github"])

SIGNATURE_HEADER = "x-hub-signature-256"
EVENT_HEADER = "x-github-event"
PING_EVENT = "ping"


@router.post("/api/github/webhook", status_code=202)
async def github_webhook(request: Request, context: ContextDep) -> JSONResponse:
    """Verify, parse and queue a pull-request event; other events are acknowledged and ignored."""
    secret = context.settings.github_webhook_secret
    if secret is None:
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    body = await request.body()
    if not verify_signature(secret.get_secret_value(), body, request.headers.get(SIGNATURE_HEADER)):
        raise HTTPException(status_code=401, detail="invalid signature")
    event_name = request.headers.get(EVENT_HEADER, "")
    if event_name == PING_EVENT:
        return JSONResponse({"pong": True}, status_code=200)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    event = parse_pull_request_event(event_name, payload)
    if event is None:
        return JSONResponse({"ignored": True}, status_code=200)
    review_id = await asyncio.to_thread(
        context.reviews.create_github, event, delivery_id=request.headers.get("x-github-delivery")
    )
    return JSONResponse({"review_id": review_id}, status_code=202)
