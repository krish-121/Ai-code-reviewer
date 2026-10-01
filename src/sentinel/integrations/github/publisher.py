"""Publish a review to a pull request — idempotently.

* The summary lives in one issue comment tagged ``<!-- sentinel:summary -->``; later
  runs edit it instead of adding another.
* Inline comments carry ``<!-- sentinel:fp=<fingerprint> -->``; a finding whose
  fingerprint is already on the PR is not posted again after a new push.
* Only lines that are part of the diff can take inline comments; other findings are
  listed in the summary.

Called by ``ReviewService.publish`` (the worker's ``publish`` job).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sentinel.core.domain.models import ChangeSet, Finding, LineKind, ReviewResult
from sentinel.integrations.github.client import GitHubClient
from sentinel.integrations.github.render import SUMMARY_MARKER, finding_comment, summary_comment

FP_RE = re.compile(r"<!-- sentinel:fp=([\w-]+) -->")
RIGHT_SIDE = "RIGHT"  # comment on the new version of the file


@dataclass
class PublishResult:
    """What was posted: finding ids per outcome, and the summary comment."""

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
    """The last line of the finding's range that GitHub accepts a comment on."""
    for line in range(f.line_end, f.line_start - 1, -1):
        if line in allowed:
            return line
    return None


class GitHubPublisher:
    """Posts one review's results to its pull request."""

    def __init__(self, client: GitHubClient, review_url: str | None = None) -> None:
        self.client = client
        self.review_url = review_url

    def publish(
        self, repo: str, number: int, head_sha: str, result: ReviewResult, pr_changeset: ChangeSet
    ) -> PublishResult:
        """Create or update the summary comment, then post new inline comments as one review."""
        out = PublishResult()
        comments, not_inline = self._inline_comments(repo, number, result, pr_changeset, out)
        body = summary_comment(result, review_url=self.review_url, not_inline=not_inline)
        self._upsert_summary(repo, number, body, out)
        if comments:
            self.client.create_review(
                repo,
                number,
                commit_id=head_sha,
                body=f"Sentinel found {len(comments)} new issue(s) in this push.",
                comments=comments,
            )
        return out

    def _inline_comments(
        self,
        repo: str,
        number: int,
        result: ReviewResult,
        pr_changeset: ChangeSet,
        out: PublishResult,
    ) -> tuple[list[dict[str, object]], list[Finding]]:
        """Comments for findings not yet on the PR, and the findings that can't be inline."""
        allowed = commentable_lines(pr_changeset)
        already_posted = {
            match.group(1)
            for comment in self.client.review_comments(repo, number)
            for match in FP_RE.finditer(comment.get("body") or "")
        }
        comments: list[dict[str, object]] = []
        not_inline: list[Finding] = []
        for finding in result.findings:
            line = _anchor(finding, allowed.get(finding.file, set()))
            if finding.fingerprint in already_posted:
                out.duplicates.append(finding.id)
            elif line is None:
                not_inline.append(finding)
                out.not_inline.append(finding.id)
            else:
                body = finding_comment(finding, self.review_url)
                comments.append(
                    {"path": finding.file, "line": line, "side": RIGHT_SIDE, "body": body}
                )
                out.posted.append(finding.id)
        return comments, not_inline

    def _upsert_summary(self, repo: str, number: int, body: str, out: PublishResult) -> None:
        """Edit Sentinel's existing summary comment, or create it on the first run."""
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
