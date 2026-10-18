"""Operational routes: health check, current user, Prometheus metrics."""

# No `from __future__ import annotations`: FastAPI evaluates route signatures.

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from sentinel import __version__
from sentinel.apps.api.dependencies import ContextDep, SessionDep, UserDep
from sentinel.infrastructure.observability.durable import render_persisted
from sentinel.infrastructure.queue import jobs

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(context: ContextDep, session: SessionDep) -> dict[str, Any]:
    """Liveness plus the facts an operator checks first (database, queue depth, provider)."""
    return {
        "status": "ok",
        "version": __version__,
        "database": context.database.dialect,
        "queue": jobs.pending(session),
        "provider": context.settings.provider,
        "auth": context.settings.auth_mode,
    }


@router.get("/api/me")
def me(user: UserDep) -> dict[str, Any]:
    """The user the request is authenticated as."""
    return {"id": user.id, "name": user.name, "is_admin": user.is_admin}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(session: SessionDep) -> str:
    """Counters and timings in the Prometheus text format."""
    return render_persisted(session)
