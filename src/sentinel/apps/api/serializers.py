"""Request bodies and JSON shapes of the HTTP API.

Routes return plain dictionaries built here, so the shape the web UI depends on is
defined in one place (mirrored in ``web/src/types.ts``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from sentinel.core.domain.models import FindingStatus
from sentinel.infrastructure.database.models import Finding as FindingRow
from sentinel.infrastructure.database.models import FindingEvent, FixAttempt, Review
from sentinel.infrastructure.database.store import Store

LOCAL_REPOSITORY = "local"
APPLICABLE_FIX_STATUSES = ("validated", "unverified")
MAX_NOTE_LENGTH = 2000


class CreateReview(BaseModel):
    """Body of ``POST /api/reviews``: review a repository on this machine."""

    path: str
    mode: str = Field(default="staged", pattern="^(staged|worktree|range|path)$")
    base: str | None = None
    head: str | None = None
    subpath: str | None = None


class UpdateFinding(BaseModel):
    """Body of ``PATCH /api/findings/{id}``: accept, dismiss or reopen a finding."""

    status: FindingStatus
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


def iso(value: datetime | None) -> str | None:
    """ISO-8601 text for a timestamp, or None."""
    return value.isoformat() if value else None


def is_local(review: Review) -> bool:
    """True when the review ran on a repository on this machine (fixes can be applied)."""
    return review.repository.kind == LOCAL_REPOSITORY


def review_item(review: Review) -> dict[str, Any]:
    """Short form of a review, used in the review list."""
    summary = review.summary or {}
    stats = summary.get("stats") or {}
    pr = review.pull_request
    pull_request = (
        {"number": pr.number, "url": pr.url, "title": pr.title, "author": pr.author} if pr else None
    )
    return {
        "id": review.id,
        "title": review.title,
        "status": review.status,
        "risk": review.risk,
        "source": review.source,
        "repository": review.repository.full_name,
        "repository_kind": review.repository.kind,
        "pull_request": pull_request,
        "counts": stats.get("by_severity", {}),
        "headline": summary.get("headline"),
        "provider": review.provider,
        "model": review.model,
        "created_at": iso(review.created_at),
        "finished_at": iso(review.finished_at),
        "duration_ms": review.duration_ms,
    }


def review_detail(review: Review, store: Store) -> dict[str, Any]:
    """Full form of a review: the list fields plus summary, stages and tool runs."""
    request = dict(review.request or {})
    runs = store.load_result(review).analysis_runs
    return {
        **review_item(review),
        "summary": review.summary,
        "stages": review.stages,
        "errors": review.errors,
        "base_ref": review.base_ref,
        "head_ref": review.head_ref,
        "usage": {"input_tokens": review.input_tokens, "output_tokens": review.output_tokens},
        "published_at": iso(review.published_at),
        "mode": request.get("mode") or request.get("kind"),
        "analysis_runs": [run.model_dump() for run in runs],
        "can_apply_fixes": is_local(review),
    }


def finding_json(row: FindingRow) -> dict[str, Any]:
    """A finding as stored, plus the fields that can change after the review."""
    return {
        **row.data,
        "status": row.status,
        "suppressed": row.suppressed,
        "suppressed_reason": row.suppressed_reason,
        "review_id": row.review_id,
    }


def event_json(event: FindingEvent) -> dict[str, Any]:
    """One entry of a finding's history."""
    return {
        "event": event.event,
        "from": event.from_status,
        "to": event.to_status,
        "note": event.note,
        "at": iso(event.created_at),
    }


def fix_json(fix: FixAttempt, repository_is_local: bool) -> dict[str, Any]:
    """A fix attempt; ``can_apply`` is true only for usable fixes on local repositories."""
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
        "created_at": iso(fix.created_at),
        "finished_at": iso(fix.finished_at),
        "can_apply": repository_is_local and fix.status in APPLICABLE_FIX_STATUSES,
    }
