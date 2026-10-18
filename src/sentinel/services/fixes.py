"""Application service for fix attempts (generate, validate, apply)."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from sentinel.bootstrap import build_fix_engine
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import FindingStatus, utcnow
from sentinel.core.fixes.engine import FixEngine, FixOutcome, apply_fix
from sentinel.infrastructure.database.models import Finding as FindingRow
from sentinel.infrastructure.database.models import FixAttempt, Review
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.resources import close_provider
from sentinel.services.reviews import (
    GITHUB_KIND,
    GitHubFactory,
    GitHubRequest,
    IntegrationNotConfiguredError,
)

EngineFactory = Callable[[Path, bool], FixEngine]


class FixNotApplicableError(SentinelError, RuntimeError):
    """The fix cannot be written to disk here (e.g. the review was of a GitHub PR)."""


class FixService:
    """Generate, validate, store and apply fixes for findings."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        engine_factory: EngineFactory | None = None,
        github_factory: GitHubFactory | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.github_factory = github_factory
        self.engine_factory = engine_factory or (
            lambda root, trusted: build_fix_engine(
                settings, load_repo_config(root), workspace=root, trusted_workspace=trusted
            )
        )

    def run(self, fix_id: str) -> FixOutcome:
        """Generate and validate a queued fix; failures are stored, not raised."""
        with self.db.transaction() as s:
            fix = s.get_one(FixAttempt, fix_id)
            row = s.get_one(FindingRow, fix.finding_id)
            finding = Store.domain_finding(row)
            review = s.get_one(Review, row.review_id)
            request = dict(review.request)
            local_path = review.request.get("path")
            fix.status = "running"
        tmp: Path | None = None
        try:
            if request.get("kind") == GITHUB_KIND:
                if self.github_factory is None:
                    raise IntegrationNotConfiguredError("GitHub integration is not configured")
                gh = GitHubRequest.from_dict(request)
                tmp = Path(tempfile.mkdtemp(prefix="sentinel-fix-"))
                self.github_factory(gh.installation_id).download_tree(gh.repo, gh.head_sha, tmp)
                root, trusted = tmp, False
            else:
                if not local_path:
                    raise RuntimeError("review has no local repository path")
                root, trusted = Path(local_path), True
            engine = self.engine_factory(root, trusted)
            try:
                outcome = engine.generate(finding, root)
            finally:
                close_provider(engine)
        except Exception as exc:
            outcome = FixOutcome(status="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
        self.save_outcome(fix_id, outcome)
        return outcome

    def save_outcome(self, fix_id: str, outcome: FixOutcome) -> None:
        """Store a fix outcome on its ``FixAttempt`` row and log it in the finding's history."""
        with self.db.transaction() as s:
            fix = s.get_one(FixAttempt, fix_id)
            fix.status = outcome.status
            fix.summary = outcome.summary
            fix.patch = outcome.patch
            fix.edits = [e.model_dump() for e in outcome.edits]
            fix.checks = [c.model_dump() for c in outcome.checks]
            fix.isolation = outcome.isolation
            fix.provider = outcome.provider
            fix.model = outcome.model
            fix.attempts = outcome.attempts
            fix.error = outcome.error
            fix.finished_at = utcnow()
            fix.original_hashes = dict(outcome.original_hashes)
            row = s.get_one(FindingRow, fix.finding_id)
            note = f"{fix.id}: {outcome.status}"
            if outcome.fallback_events:
                note += "; AI fallback: " + "; ".join(outcome.fallback_events)
            Store(s).record_event(row, "fix_generated", None, note)

    @staticmethod
    def outcome_of(fix: FixAttempt) -> FixOutcome:
        """Rebuild the ``FixOutcome`` from a stored row (needed to apply it later)."""
        known = ("validated", "unverified", "failed", "error")
        return FixOutcome.model_validate(
            {
                "status": fix.status if fix.status in known else "error",
                "summary": fix.summary or "",
                "patch": fix.patch or "",
                "edits": fix.edits,
                "original_hashes": fix.original_hashes or {},
                "checks": fix.checks,
                "attempts": fix.attempts,
                "isolation": fix.isolation or "none",
                "error": fix.error,
                "provider": fix.provider,
                "model": fix.model,
            }
        )

    def apply(self, fix_id: str) -> list[str]:
        """Write a fix into the local repository; returns the files written."""
        with self.db.transaction() as s:
            fix = s.get_one(FixAttempt, fix_id)
            row = s.get_one(FindingRow, fix.finding_id)
            review = s.get_one(Review, row.review_id)
            local_path = review.request.get("path")
            if review.request.get("kind") == GITHUB_KIND or not local_path:
                raise FixNotApplicableError(
                    "fixes for GitHub pull requests are applied by pushing the patch; "
                    "download it instead"
                )
            written = apply_fix(Path(local_path), self.outcome_of(fix))
            fix.status = "applied"
            store = Store(s)
            store.set_status(row, FindingStatus.FIXED, None, note=f"applied {fix.id}")
            return written
