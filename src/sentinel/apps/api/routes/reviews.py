"""Review routes: list, start, read, and stream the progress of reviews.

Called by the web UI (``web/src/api.ts``). Starting a review only *queues* it
(``ReviewService.create_local``); the worker runs the pipeline, and the browser follows
along through the Server-Sent Events stream at ``/api/reviews/{id}/events``.
"""

# No `from __future__ import annotations`: FastAPI evaluates route signatures.

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from sentinel.analysis.diff.git import GitError
from sentinel.apps.api.dependencies import (
    MUTATING,
    ContextDep,
    SessionDep,
    UserDep,
    review_or_404,
)
from sentinel.apps.api.serializers import CreateReview, finding_json, review_detail, review_item
from sentinel.core.domain.models import ReviewStatus
from sentinel.infrastructure.database.models import Review
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.workspaces import LocalRequest, authorize_root

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
FINISHED_STATUSES = {ReviewStatus.COMPLETED, ReviewStatus.PARTIAL, ReviewStatus.FAILED}
PROGRESS_POLL_SECONDS = 0.5
MAX_PROGRESS_POLLS = 3600  # stop streaming after ~30 minutes
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("")
def list_reviews(
    session: SessionDep,
    user: UserDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """The current user's most recent reviews, newest first."""
    return [review_item(r) for r in Store(session).list_reviews(user, limit=limit)]


@router.post("", status_code=202, dependencies=MUTATING)
def create_review(
    body: CreateReview, context: ContextDep, session: SessionDep, user: UserDep
) -> dict[str, str]:
    """Queue a review of a repository on this machine and return its id."""
    path = Path(body.path).expanduser().resolve()
    if not any(
        path == root or path.is_relative_to(root) for root in context.settings.allowed_roots()
    ):
        raise HTTPException(
            status_code=403,
            detail="path is outside the directories this server may review "
            "(set SENTINEL_LOCAL_ROOTS)",
        )
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"{path} is not a directory")
    try:
        authorize_root(path, context.settings.allowed_roots())
    except GitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    session.commit()  # release the request transaction before the service opens its own
    request = LocalRequest(
        path=str(path),
        mode=body.mode,
        base=body.base,
        head=body.head,
        subpath=body.subpath,
        allowed_roots=[str(p) for p in context.settings.allowed_roots()],
    )
    review_id = context.reviews.create_local(user.id, request, enqueue=True)
    return {"id": review_id}


@router.get("/{review_id}")
def get_review(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """One review with its summary, stages and tool runs."""
    store = Store(session)
    return review_detail(review_or_404(store, user, review_id), store)


@router.get("/{review_id}/findings")
def get_findings(
    review_id: str, session: SessionDep, user: UserDep, include_suppressed: bool = True
) -> list[dict[str, Any]]:
    """The review's findings, optionally including suppressed ones."""
    review = review_or_404(Store(session), user, review_id)
    return [finding_json(r) for r in review.findings if include_suppressed or not r.suppressed]


@router.get("/{review_id}/files")
def get_files(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """The parsed diff (changed files with hunks, plus skipped files)."""
    review = review_or_404(Store(session), user, review_id)
    return review.changeset or {"files": [], "skipped": []}


@router.get("/{review_id}/graph")
def get_graph(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """The code-graph subgraph shown in the architecture view."""
    store = Store(session)
    return store.graph(review_or_404(store, user, review_id)).to_dict()


@router.get("/{review_id}/source")
def get_source(review_id: str, path: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """A file's content from the review's redacted snapshot (never read from disk)."""
    review = review_or_404(Store(session), user, review_id)
    content = (review.sources or {}).get(path)
    if content is None:
        raise HTTPException(status_code=404, detail="file not in this review's snapshot")
    return {"path": path, "content": content}


@router.get("/{review_id}/events")
async def review_events(
    review_id: str, request: Request, context: ContextDep, user: UserDep
) -> StreamingResponse:
    """Stream stage progress as Server-Sent Events until the review finishes."""
    with context.database.transaction() as session:
        review_or_404(Store(session), user, review_id)
    stream = progress_events(context.database, review_id, request)
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)


async def progress_events(
    database: Database, review_id: str, request: Request
) -> AsyncIterator[str]:
    """Poll the review row and yield a ``progress`` event whenever it changes.

    Polling the database (instead of an in-process pub/sub) works no matter which worker
    process runs the review. Ends with a ``done`` event, or when the browser disconnects.
    """
    last_payload = ""
    for _ in range(MAX_PROGRESS_POLLS):
        if await request.is_disconnected():
            return
        status, stages = await asyncio.to_thread(_read_progress, database, review_id)
        payload = json.dumps({"status": status, "stages": stages})
        if payload != last_payload:
            last_payload = payload
            yield f"event: progress\ndata: {payload}\n\n"
        if status in FINISHED_STATUSES:
            yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
            return
        await asyncio.sleep(PROGRESS_POLL_SECONDS)


def _read_progress(database: Database, review_id: str) -> tuple[str, list[Any]]:
    with database.transaction() as session:
        review = session.get_one(Review, review_id)
        return review.status, list(review.stages or [])
