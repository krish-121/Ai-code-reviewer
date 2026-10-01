"""Application services: create, run and publish reviews.

Sits between the delivery mechanisms (CLI, API, worker) and the review engine. It owns
transactions and the lifecycle of a ``Review`` row: queued -> running (stage updates
streamed into the row) -> completed / partial / failed.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.bootstrap import FROM_SETTINGS, build_orchestrator
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import ReviewResult, StageRecord, utcnow
from sentinel.core.domain.ports import AIProvider, ProgressReporter
from sentinel.infrastructure.database.models import Review, User
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.infrastructure.queue import jobs
from sentinel.integrations.github.client import GitHubClient
from sentinel.integrations.github.publisher import GitHubPublisher, PublishResult
from sentinel.integrations.github.webhooks import PullRequestEvent
from sentinel.services.workspaces import LocalRequest, prepare_local

log = logging.getLogger("sentinel.services")

# Returns the provider to use: an AIProvider, None (no AI), or FROM_SETTINGS.
AIFactory = Callable[[], AIProvider | None | str]
# Returns a GitHub client for an App installation id (None: token auth).
GitHubFactory = Callable[[int | None], GitHubClient]
GITHUB_KIND = "github"
GITHUB_SOURCE = "github_pr"
LOCAL_USER = "local"
PUBLISH_ATTEMPTS = 6


class IntegrationNotConfiguredError(SentinelError, RuntimeError):
    """The GitHub integration is needed but no token or App credentials are set."""


class DBProgress:
    """Persist stage transitions so any process (API/SSE) can show live progress."""

    def __init__(self, db: Database, review_id: str, also: ProgressReporter | None = None) -> None:
        self.db = db
        self.review_id = review_id
        self.also = also
        self.stages: dict[str, StageRecord] = {}

    def stage_changed(self, stage: StageRecord) -> None:
        """Write the new stage list to the review row (and forward to ``also``)."""
        self.stages[stage.name.value] = stage.model_copy()
        with self.db.transaction() as s:
            review = s.get(Review, self.review_id)
            if review is not None:
                Store(s).update_stages(review, list(self.stages.values()))
        if self.also is not None:
            self.also.stage_changed(stage)


@dataclass
class GitHubRequest:
    """What a GitHub review needs to fetch its pull request (stored on the review row)."""

    repo: str
    number: int
    head_sha: str
    installation_id: int | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubRequest:
        """Read the request back from ``Review.request``."""
        return cls(
            repo=str(data["repo"]),
            number=int(data["number"]),
            head_sha=str(data.get("head_sha") or ""),
            installation_id=data.get("installation_id"),
        )


class ReviewService:
    """Create, run and publish reviews (the use cases behind CLI, API and worker)."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        ai_factory: AIFactory | None = None,
        github_factory: GitHubFactory | None = None,
        public_url: str | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.ai_factory = ai_factory or (lambda: FROM_SETTINGS)
        self.github_factory = github_factory
        self.public_url = public_url.rstrip("/") if public_url else None

    # ------------------------------------------------------------------ creation
    def create_local(self, user_id: str, request: LocalRequest, *, enqueue: bool) -> str:
        """Create a review of a local repository; queue it for the worker if ``enqueue``."""
        path = str(Path(request.path).expanduser().resolve())
        request = request.model_copy(update={"path": path})
        with self.db.transaction() as s:
            store = Store(s)
            user = store.local_user() if user_id == LOCAL_USER else s.get_one(User, user_id)
            repo = store.repository(user, Path(path).name, kind="local", local_path=path)
            review = store.create_review(
                repo,
                request=request.model_dump(),
                source=request.mode,
                title=_local_title(request),
            )
            if enqueue:
                jobs.enqueue(s, jobs.REVIEW_JOB, {"review_id": review.id})
            return review.id

    def create_github(
        self, event: PullRequestEvent, *, enqueue: bool = True, publish: bool = True
    ) -> str:
        """Create a review for a pull-request event.

        The webhook queues it for a worker and publishes the results to the PR. The CLI
        (``sentinel review --pr``) runs it itself and never posts anything
        (``enqueue=False, publish=False``).
        """
        with self.db.transaction() as s:
            store = Store(s)
            owner = store.installation_owner(event.installation_id)
            repo = store.repository(
                owner, event.repo, kind=GITHUB_KIND, installation_id=event.installation_id
            )
            pr = store.pull_request(
                repo,
                event.number,
                title=event.title,
                author=event.author,
                url=event.url,
                head_sha=event.head_sha,
                base_sha=event.base_sha,
            )
            review = store.create_review(
                repo,
                request={
                    "kind": GITHUB_KIND,
                    "repo": event.repo,
                    "number": event.number,
                    "head_sha": event.head_sha,
                    "installation_id": event.installation_id,
                    "publish": publish,
                },
                source=GITHUB_SOURCE,
                title=f"#{event.number} {event.title}",
                pull_request=pr,
            )
            if enqueue:
                jobs.enqueue(s, jobs.REVIEW_JOB, {"review_id": review.id})
            return review.id

    # ------------------------------------------------------------------ running
    def run(self, review_id: str, progress: ProgressReporter | None = None) -> ReviewResult:
        """Run a created review to the end and save the result.

        GitHub reviews also queue a ``publish`` job (unless created with ``publish=False``).
        If anything raises, the review is marked failed and the exception is re-raised (the
        worker then retries the job).
        """
        with self.db.transaction() as s:
            review = s.get_one(Review, review_id)
            request = dict(review.request)
        reporter = DBProgress(self.db, review_id, progress)
        try:
            if request.get("kind") == GITHUB_KIND:
                result = self._run_github(review_id, GitHubRequest.from_dict(request), reporter)
            else:
                result = self._run_local(review_id, LocalRequest(**request), reporter)
        except Exception as exc:
            with self.db.transaction() as s:
                Store(s).mark_failed(s.get_one(Review, review_id), f"{type(exc).__name__}: {exc}")
            raise
        with self.db.transaction() as s:
            review = s.get_one(Review, review_id)
            Store(s).save_result(review, result)
            if request.get("kind") == GITHUB_KIND and request.get("publish", True):
                jobs.enqueue(
                    s, jobs.PUBLISH_JOB, {"review_id": review_id}, max_attempts=PUBLISH_ATTEMPTS
                )
        return result

    def _run_local(
        self, review_id: str, request: LocalRequest, progress: ProgressReporter
    ) -> ReviewResult:
        with prepare_local(request) as ws:
            config = load_repo_config(ws.workspace)
            orchestrator = build_orchestrator(
                self.settings,
                config,
                workspace=ws.workspace,
                ai=self.ai_factory(),
                progress=progress,
            )
            return orchestrator.review(
                ws.changeset, ws.workspace, repository=ws.repository, review_id=review_id
            )

    def _run_github(
        self, review_id: str, request: GitHubRequest, progress: ProgressReporter
    ) -> ReviewResult:
        """Fetch the PR diff and a snapshot of its head commit, then review it as untrusted."""
        if self.github_factory is None:
            raise IntegrationNotConfiguredError("GitHub integration is not configured")
        client = self.github_factory(request.installation_id)
        pr = client.pull(request.repo, request.number)
        head_sha = request.head_sha or str((pr.get("head") or {}).get("sha", ""))
        changeset = parse_unified_diff(
            client.pull_diff(request.repo, request.number), source=GITHUB_SOURCE
        )
        changeset.title = f"#{request.number} {pr.get('title', '')}".strip()
        changeset.base_ref = (pr.get("base") or {}).get("sha")
        changeset.head_ref = head_sha
        workspace = Path(tempfile.mkdtemp(prefix="sentinel-pr-"))
        try:
            client.download_tree(request.repo, head_sha, workspace)
            config = load_repo_config(workspace)
            orchestrator = build_orchestrator(
                self.settings,
                config,
                workspace=workspace,
                ai=self.ai_factory(),
                progress=progress,
                trusted_workspace=False,
            )
            return orchestrator.review(
                changeset, workspace, repository=request.repo, review_id=review_id
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    # ------------------------------------------------------------------ publishing
    def publish(self, review_id: str) -> PublishResult:
        """Post (or update) the review's comments on its pull request."""
        if self.github_factory is None:
            raise IntegrationNotConfiguredError("GitHub integration is not configured")
        with self.db.transaction() as s:
            review = s.get_one(Review, review_id)
            request = GitHubRequest.from_dict(review.request)
            result = Store(s).load_result(review)
        client = self.github_factory(request.installation_id)
        pr_changeset = parse_unified_diff(client.pull_diff(request.repo, request.number))
        url = f"{self.public_url}/reviews/{review_id}" if self.public_url else None
        published = GitHubPublisher(client, url).publish(
            request.repo, request.number, request.head_sha, result, pr_changeset
        )
        with self.db.transaction() as s:
            review = s.get_one(Review, review_id)
            review.published_at = utcnow()
        log.info(
            "published review=%s posted=%d duplicates=%d not_inline=%d",
            review_id,
            len(published.posted),
            len(published.duplicates),
            len(published.not_inline),
        )
        return published


def _local_title(request: LocalRequest) -> str:
    """Human-readable title such as 'Staged changes in shop'."""
    name = Path(request.path).name
    return {
        "staged": f"Staged changes in {name}",
        "worktree": f"Uncommitted changes in {name}",
        "range": f"{request.base or 'HEAD~1'}...{request.head or 'HEAD'} in {name}",
        "path": f"Review of {request.subpath or name}",
    }.get(request.mode, name)
