"""HTTP API (FastAPI).

Delivery only: every route translates HTTP into calls on the application services and
back. Tenancy is enforced through ``Store`` lookups that take the current user; a
review a user may not see is indistinguishable from one that doesn't exist (404).

Browser safety for the local, no-login mode: the server binds to localhost, rejects
foreign ``Host`` headers (DNS rebinding), and requires an ``X-Sentinel-Client`` header on
state-changing requests, which cross-site forms cannot send without a CORS preflight.
"""

# NOTE: no `from __future__ import annotations` here: FastAPI must evaluate the
# Annotated[..., Depends()] aliases defined inside create_app() at definition time.

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sentinel import __version__
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import FindingStatus, ReviewStatus
from sentinel.infrastructure.database.models import Finding as FindingRow
from sentinel.infrastructure.database.models import FixAttempt, Review, User
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.infrastructure.observability.metrics import METRICS
from sentinel.infrastructure.queue import jobs
from sentinel.integrations.github.webhooks import parse_pull_request_event, verify_signature
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService
from sentinel.services.workspaces import LocalRequest

TERMINAL = {ReviewStatus.COMPLETED.value, ReviewStatus.PARTIAL.value, ReviewStatus.FAILED.value}
STATIC_DIR = Path(__file__).parent / "static"


class CreateReview(BaseModel):
    path: str
    mode: str = Field(default="staged", pattern="^(staged|worktree|range|path)$")
    base: str | None = None
    head: str | None = None
    subpath: str | None = None


class UpdateFinding(BaseModel):
    status: FindingStatus
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- serializers


def review_item(review: Review) -> dict[str, Any]:
    summary = review.summary or {}
    stats = summary.get("stats") or {}
    pr = review.pull_request
    return {
        "id": review.id,
        "title": review.title,
        "status": review.status,
        "risk": review.risk,
        "source": review.source,
        "repository": review.repository.full_name,
        "repository_kind": review.repository.kind,
        "pull_request": (
            {"number": pr.number, "url": pr.url, "title": pr.title, "author": pr.author}
            if pr
            else None
        ),
        "counts": stats.get("by_severity", {}),
        "headline": summary.get("headline"),
        "provider": review.provider,
        "model": review.model,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "finished_at": review.finished_at.isoformat() if review.finished_at else None,
        "duration_ms": review.duration_ms,
    }


def review_detail(review: Review, store: Store) -> dict[str, Any]:
    data = review_item(review)
    request = dict(review.request or {})
    runs = store.load_result(review).analysis_runs
    data.update(
        {
            "summary": review.summary,
            "stages": review.stages,
            "errors": review.errors,
            "base_ref": review.base_ref,
            "head_ref": review.head_ref,
            "usage": {"input_tokens": review.input_tokens, "output_tokens": review.output_tokens},
            "published_at": review.published_at.isoformat() if review.published_at else None,
            "mode": request.get("mode") or request.get("kind"),
            "analysis_runs": [r.model_dump() for r in runs],
            "can_apply_fixes": review.repository.kind == "local",
        }
    )
    return data


def finding_json(row: FindingRow) -> dict[str, Any]:
    data = dict(row.data)
    data.update(
        {
            "status": row.status,
            "suppressed": row.suppressed,
            "suppressed_reason": row.suppressed_reason,
            "review_id": row.review_id,
        }
    )
    return data


def fix_json(fix: FixAttempt, can_apply: bool) -> dict[str, Any]:
    return {
        "id": fix.id,
        "finding_id": fix.finding_id,
        "status": fix.status,
        "summary": fix.summary,
        "patch": fix.patch,
        "checks": fix.checks,
        "isolation": fix.isolation,
        "provider": fix.provider,
        "model": fix.model,
        "attempts": fix.attempts,
        "error": fix.error,
        "created_at": fix.created_at.isoformat() if fix.created_at else None,
        "finished_at": fix.finished_at.isoformat() if fix.finished_at else None,
        "can_apply": can_apply and fix.status in ("validated", "unverified"),
    }


# --------------------------------------------------------------------------- app factory


def create_app(
    settings: Settings,
    *,
    db: Database | None = None,
    reviews: ReviewService | None = None,
    fixes: FixService | None = None,
    worker_factory: Callable[[], Any] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    database = db or Database(settings.database_url)
    database.create_all()
    review_service = reviews or ReviewService(database, settings, public_url=settings.public_url)
    fix_service = fixes or FixService(database, settings)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        thread = None
        if worker_factory is not None:
            worker = worker_factory()
            thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
            thread.start()
        yield
        stop.set()
        if thread is not None:
            thread.join(timeout=5)

    app = FastAPI(title="Sentinel", version=__version__, lifespan=lifespan)
    if settings.auth_mode == "local":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
        )

    # ------------------------------------------------------------------ dependencies
    def get_session() -> Iterator[Session]:
        with database.transaction() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def get_user(
        session: SessionDep, authorization: Annotated[str | None, Header()] = None
    ) -> User:
        store = Store(session)
        if settings.auth_mode == "local":
            return store.local_user()
        token = (authorization or "").removeprefix("Bearer ").strip()
        user = store.user_by_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail="missing or invalid API token")
        return user

    UserDep = Annotated[User, Depends(get_user)]

    def csrf(x_sentinel_client: Annotated[str | None, Header()] = None) -> None:
        if not x_sentinel_client:
            raise HTTPException(status_code=403, detail="missing X-Sentinel-Client header")

    Mutating = Depends(csrf)

    def review_or_404(store: Store, user: User, review_id: str) -> Review:
        review = store.review_for(user, review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="review not found")
        return review

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health(session: SessionDep) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "database": database.dialect,
            "queue": jobs.pending(session),
            "provider": settings.provider,
            "auth": settings.auth_mode,
        }

    @app.get("/api/me")
    def me(user: UserDep) -> dict[str, Any]:
        return {"id": user.id, "name": user.name, "is_admin": user.is_admin}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return METRICS.render()

    # ------------------------------------------------------------------ reviews
    @app.get("/api/reviews")
    def list_reviews(
        session: SessionDep, user: UserDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[dict[str, Any]]:
        return [review_item(r) for r in Store(session).list_reviews(user, limit=limit)]

    @app.post("/api/reviews", status_code=202, dependencies=[Mutating])
    def create_review(body: CreateReview, session: SessionDep, user: UserDep) -> dict[str, str]:
        path = Path(body.path).expanduser().resolve()
        roots = settings.allowed_roots()
        if not any(path == r or path.is_relative_to(r) for r in roots):
            raise HTTPException(
                status_code=403,
                detail="path is outside the directories this server may review "
                "(set SENTINEL_LOCAL_ROOTS)",
            )
        if not path.is_dir():
            raise HTTPException(status_code=400, detail=f"{path} is not a directory")
        session.commit()  # release the request transaction before the service opens its own
        review_id = review_service.create_local(
            user.id,
            LocalRequest(
                path=str(path), mode=body.mode, base=body.base, head=body.head, subpath=body.subpath
            ),
            enqueue=True,
        )
        return {"id": review_id}

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        store = Store(session)
        return review_detail(review_or_404(store, user, review_id), store)

    @app.get("/api/reviews/{review_id}/findings")
    def get_findings(
        review_id: str, session: SessionDep, user: UserDep, include_suppressed: bool = True
    ) -> list[dict[str, Any]]:
        review = review_or_404(Store(session), user, review_id)
        return [finding_json(r) for r in review.findings if include_suppressed or not r.suppressed]

    @app.get("/api/reviews/{review_id}/files")
    def get_files(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        review = review_or_404(Store(session), user, review_id)
        return review.changeset or {"files": [], "skipped": []}

    @app.get("/api/reviews/{review_id}/graph")
    def get_graph(review_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        store = Store(session)
        review = review_or_404(store, user, review_id)
        return store.graph(review).to_dict()

    @app.get("/api/reviews/{review_id}/source")
    def get_source(review_id: str, path: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        # Served only from the review's redacted snapshot: never from the filesystem.
        review = review_or_404(Store(session), user, review_id)
        content = (review.sources or {}).get(path)
        if content is None:
            raise HTTPException(status_code=404, detail="file not in this review's snapshot")
        return {"path": path, "content": content}

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str, request: Request, user: UserDep) -> StreamingResponse:
        with database.transaction() as s:
            review_or_404(Store(s), user, review_id)

        def snapshot() -> tuple[str, list[Any]]:
            with database.transaction() as s:
                row = s.get_one(Review, review_id)
                return row.status, list(row.stages or [])

        async def stream() -> AsyncIterator[str]:
            last = ""
            for _ in range(3600):  # hard stop after ~30 minutes
                if await request.is_disconnected():
                    return
                status, stages = await asyncio.to_thread(snapshot)
                payload = json.dumps({"status": status, "stages": stages})
                if payload != last:
                    last = payload
                    yield f"event: progress\ndata: {payload}\n\n"
                if status in TERMINAL:
                    yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ findings
    def finding_or_404(store: Store, user: User, finding_id: str) -> FindingRow:
        row = store.finding_for(user, finding_id)
        if row is None:
            raise HTTPException(status_code=404, detail="finding not found")
        return row

    @app.get("/api/findings/{finding_id}")
    def get_finding(finding_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        store = Store(session)
        row = finding_or_404(store, user, finding_id)
        can_apply = row.review.repository.kind == "local"
        return {
            "finding": finding_json(row),
            "events": [
                {
                    "event": e.event,
                    "from": e.from_status,
                    "to": e.to_status,
                    "note": e.note,
                    "at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in store.events(row.id)
            ],
            "fixes": [fix_json(f, can_apply) for f in store.fixes_for_finding(row.id)],
        }

    @app.patch("/api/findings/{finding_id}", dependencies=[Mutating])
    def update_finding(
        finding_id: str, body: UpdateFinding, session: SessionDep, user: UserDep
    ) -> dict[str, Any]:
        store = Store(session)
        row = finding_or_404(store, user, finding_id)
        store.set_status(row, body.status, user, body.note)
        return finding_json(row)

    @app.post("/api/findings/{finding_id}/fix", status_code=202, dependencies=[Mutating])
    def request_fix(finding_id: str, session: SessionDep, user: UserDep) -> dict[str, str]:
        store = Store(session)
        row = finding_or_404(store, user, finding_id)
        fix = store.create_fix(row)
        jobs.enqueue(session, "fix", {"fix_id": fix.id}, max_attempts=1)
        return {"id": fix.id}

    def fix_or_404(store: Store, user: User, fix_id: str) -> FixAttempt:
        fix = store.fix_for(user, fix_id)
        if fix is None:
            raise HTTPException(status_code=404, detail="fix not found")
        return fix

    @app.get("/api/fixes/{fix_id}")
    def get_fix(fix_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        store = Store(session)
        fix = fix_or_404(store, user, fix_id)
        finding = session.get_one(FindingRow, fix.finding_id)
        return fix_json(fix, finding.review.repository.kind == "local")

    @app.get("/api/fixes/{fix_id}/patch")
    def get_patch(fix_id: str, session: SessionDep, user: UserDep) -> Response:
        fix = fix_or_404(Store(session), user, fix_id)
        return Response(
            fix.patch or "",
            media_type="text/x-diff",
            headers={"Content-Disposition": f'attachment; filename="{fix.id}.patch"'},
        )

    @app.post("/api/fixes/{fix_id}/apply", dependencies=[Mutating])
    def apply_fix_route(fix_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
        fix_or_404(Store(session), user, fix_id)
        session.commit()
        try:
            written = fix_service.apply(fix_id)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"applied": written}

    @app.post("/api/fixes/{fix_id}/reject", dependencies=[Mutating])
    def reject_fix(fix_id: str, session: SessionDep, user: UserDep) -> dict[str, str]:
        fix = fix_or_404(Store(session), user, fix_id)
        fix.status = "rejected"
        return {"status": fix.status}

    # ------------------------------------------------------------------ GitHub
    @app.post("/api/github/webhook", status_code=202)
    async def github_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        secret = settings.github_webhook_secret
        if secret is None:
            raise HTTPException(status_code=503, detail="webhook secret not configured")
        signature = request.headers.get("x-hub-signature-256")
        if not verify_signature(secret.get_secret_value(), body, signature):
            raise HTTPException(status_code=401, detail="invalid signature")
        event_name = request.headers.get("x-github-event", "")
        if event_name == "ping":
            return JSONResponse({"pong": True}, status_code=200)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        event = parse_pull_request_event(event_name, payload)
        if event is None:
            return JSONResponse({"ignored": True}, status_code=200)
        review_id = await asyncio.to_thread(review_service.create_github, event)
        return JSONResponse({"review_id": review_id}, status_code=202)

    # ------------------------------------------------------------------ web UI
    ui = static_dir or STATIC_DIR
    index = ui / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (ui / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(ui.resolve()):
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return PlainTextResponse(
            "Sentinel API is running. Build the web UI with `npm run build` in web/.",
            status_code=200,
        )

    return app
