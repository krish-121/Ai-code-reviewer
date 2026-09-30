"""Publish a review to a pull request — idempotently.

* The summary lives in one issue comment tagged ``<!-- sentinel:summary -->``; later
  runs edit it instead of adding another.
* Inline comments carry ``<!-- sentinel:fp=<fingerprint> -->``; a finding whose
  fingerprint is already on the PR is not posted again after a new push.
* Only lines that are part of the diff can take inline comments; other findings are
  listed in the summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sentinel.core.domain.models import ChangeSet, Finding, LineKind, ReviewResult
from sentinel.integrations.github.client import GitHubClient
from sentinel.integrations.github.render import SUMMARY_MARKER, finding_comment, summary_comment

FP_RE = re.compile(r"<!-- sentinel:fp=([0-9a-f]+) -->")


@dataclass
class PublishResult:
    summary_comment_id: int | None = None
    summary_updated: bool = False
    posted: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    not_inline: list[str] = field(default_factory=list)


def commentable_lines(changeset: ChangeSet) -> dict[str, set[int]]:
    """New-side line numbers GitHub accepts review comments on (added + context lines)."""
    out: dict[str, set[int]] = {}
    for f in changeset.files:
        lines = out.setdefault(f.path, set())
        for h in f.hunks:
            for ln in h.lines:
                if ln.kind is not LineKind.REMOVED and ln.new_lineno is not None:
                    lines.add(ln.new_lineno)
    return out


def _anchor(f: Finding, allowed: set[int]) -> int | None:
    for line in range(f.line_end, f.line_start - 1, -1):
        if line in allowed:
            return line
    return None


class GitHubPublisher:
    def __init__(self, client: GitHubClient, review_url: str | None = None) -> None:
        self.client = client
        self.review_url = review_url

    def publish(
        self, repo: str, number: int, head_sha: str, result: ReviewResult, pr_changeset: ChangeSet
    ) -> PublishResult:
        out = PublishResult()
        allowed = commentable_lines(pr_changeset)
        existing = {
            m.group(1)
            for c in self.client.review_comments(repo, number)
            for m in FP_RE.finditer(c.get("body") or "")
        }
        comments = []
        not_inline: list[Finding] = []
        for f in result.findings:
            line = _anchor(f, allowed.get(f.file, set()))
            if f.fingerprint in existing:
                out.duplicates.append(f.id)
                continue
            if line is None:
                not_inline.append(f)
                out.not_inline.append(f.id)
                continue
            comments.append(
                {
                    "path": f.file,
                    "line": line,
                    "side": "RIGHT",
                    "body": finding_comment(f, self.review_url),
                }
            )
            out.posted.append(f.id)
        body = summary_comment(result, review_url=self.review_url, not_inline=not_inline)
        previous = next(
            (
                c
                for c in self.client.issue_comments(repo, number)
                if SUMMARY_MARKER in (c.get("body") or "")
            ),
            None,
        )
        if previous is not None:
            self.client.update_issue_comment(repo, int(previous["id"]), body)
            out.summary_comment_id = int(previous["id"])
            out.summary_updated = True
        else:
            created = self.client.create_issue_comment(repo, number, body)
            out.summary_comment_id = int(created["id"])
        if comments:
            self.client.create_review(
                repo,
                number,
                commit_id=head_sha,
                body=f"Sentinel found {len(comments)} new issue(s) in this push.",
                comments=comments,
            )
        return out
