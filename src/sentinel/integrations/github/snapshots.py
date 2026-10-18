"""Reject moving pull requests instead of mixing diff, tree and comment revisions."""

from __future__ import annotations

from typing import Any

from sentinel.integrations.github.client import GitHubClient


class SupersededReviewError(RuntimeError):
    """The pull request no longer has the revision that this review requested."""


def require_revision(
    client: GitHubClient, repo: str, number: int, head: str, base: str | None
) -> dict[str, Any]:
    """Check both sides of a PR; an absent head is never a stable snapshot."""
    pr = client.pull(repo, number)
    if not head or pr.get("head", {}).get("sha") != head:
        raise SupersededReviewError("pull request head changed; this review is superseded")
    if base and pr.get("base", {}).get("sha") != base:
        raise SupersededReviewError("pull request base changed; this review is superseded")
    return pr
