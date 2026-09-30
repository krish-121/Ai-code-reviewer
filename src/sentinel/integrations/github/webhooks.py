"""GitHub webhook verification and parsing."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

REVIEW_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of ``X-Hub-Signature-256``."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


@dataclass(frozen=True)
class PullRequestEvent:
    action: str
    repo: str
    number: int
    title: str
    author: str | None
    url: str | None
    head_sha: str
    base_sha: str | None
    installation_id: int | None
    draft: bool


def parse_pull_request_event(event: str, payload: dict[str, Any]) -> PullRequestEvent | None:
    """Return the PR event if it should trigger a review, else None."""
    if event != "pull_request":
        return None
    action = str(payload.get("action", ""))
    pr = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name")
    if action not in REVIEW_ACTIONS or not pr or not repo:
        return None
    if pr.get("draft") and action != "ready_for_review":
        return None
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    installation = (payload.get("installation") or {}).get("id")
    return PullRequestEvent(
        action=action,
        repo=str(repo),
        number=int(pr["number"]),
        title=str(pr.get("title", "")),
        author=(pr.get("user") or {}).get("login"),
        url=pr.get("html_url"),
        head_sha=str(head.get("sha", "")),
        base_sha=base.get("sha"),
        installation_id=int(installation) if installation is not None else None,
        draft=bool(pr.get("draft")),
    )
