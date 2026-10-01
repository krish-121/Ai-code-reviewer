"""Data-access layer: translate between domain objects and rows, and enforce tenancy.

Every read that takes a ``User`` is scoped: a user only sees repositories they own
(admins see everything). This is the single place repository isolation is enforced,
and it is tested directly.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sentinel.core.domain.graph import CodeGraph
from sentinel.core.domain.models import (
    AnalysisRun,
    ChangeSet,
    FindingStatus,
    ReviewResult,
    ReviewStatus,
    ReviewSummary,
    StageRecord,
    TokenUsage,
    new_id,
    utcnow,
)
from sentinel.core.domain.models import Finding as DomainFinding
from sentinel.infrastructure.database.models import (
    AnalysisRunRow,
    CodeGraphSnapshot,
    Finding,
    FindingEvent,
    FixAttempt,
    GithubInstallation,
    PullRequest,
    Repository,
    Review,
    User,
)

LOCAL_USER_ID = "local"


def hash_token(token: str) -> str:
    """SHA-256 of an API token; only the hash is stored."""
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    """All database reads and writes, scoped by user.

    One ``Store`` wraps one SQLAlchemy session (one transaction). Every lookup that takes a ``user``
    enforces tenancy: it returns None for rows the user may not see.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ users
    def local_user(self) -> User:
        """The single user of local (no-login) mode, created on first use."""
        user = self.session.get(User, LOCAL_USER_ID)
        if user is None:
            user = User(id=LOCAL_USER_ID, name="local", is_admin=True)
            self.session.add(user)
            self.session.flush()
        return user

    def create_user(self, name: str, *, is_admin: bool = False) -> tuple[User, str]:
        """Create an API user; returns the user and its token (shown once, stored hashed)."""
        token = "snt_" + secrets.token_urlsafe(32)
        user = User(id=new_id("U"), name=name, token_hash=hash_token(token), is_admin=is_admin)
        self.session.add(user)
        self.session.flush()
        return user, token

    def user_by_token(self, token: str) -> User | None:
        """The user owning this API token, or None."""
        if not token:
            return None
        return self.session.scalar(select(User).where(User.token_hash == hash_token(token)))

    def system_user(self, name: str = "github") -> User:
        """A non-admin owner for repositories of unlinked GitHub installations."""
        user = self.session.get(User, f"system-{name}")
        if user is None:
            user = User(id=f"system-{name}", name=name, is_admin=False)
            self.session.add(user)
            self.session.flush()
        return user

    def link_installation(self, installation_id: int, user: User, account: str | None) -> None:
        """Make ``user`` the owner of a GitHub App installation's repositories."""
        row = self.session.get(GithubInstallation, installation_id)
        if row is None:
            self.session.add(
                GithubInstallation(
                    installation_id=installation_id, user_id=user.id, account=account
                )
            )
        else:
            row.user_id = user.id
            row.account = account or row.account
        self.session.flush()

    def installation_owner(self, installation_id: int | None) -> User:
        """The user who owns an installation (a system user if none is linked)."""
        if installation_id is not None:
            row = self.session.get(GithubInstallation, installation_id)
            if row is not None:
                user = self.session.get(User, row.user_id)
                if user is not None:
                    return user
        return self.system_user("github")

    # ------------------------------------------------------------------ access
    @staticmethod
    def can_access(user: User, repo: Repository) -> bool:
        """True when ``user`` may see ``repo`` (owner or admin)."""
        return user.is_admin or repo.owner_id == user.id

    # ------------------------------------------------------------------ repositories
    def repository(
        self,
        owner: User,
        full_name: str,
        *,
        kind: str = "local",
        local_path: str | None = None,
        installation_id: int | None = None,
    ) -> Repository:
        """Get or create the user's repository row with this name."""
        repo = self.session.scalar(
            select(Repository).where(
                Repository.owner_id == owner.id, Repository.full_name == full_name
            )
        )
        if repo is None:
            repo = Repository(
                id=new_id("P"),
                owner_id=owner.id,
                full_name=full_name,
                kind=kind,
                local_path=local_path,
                github_installation_id=installation_id,
            )
            self.session.add(repo)
            self.session.flush()
        else:
            if local_path:
                repo.local_path = local_path
            if installation_id is not None:
                repo.github_installation_id = installation_id
        return repo

    def pull_request(self, repo: Repository, number: int, **fields: Any) -> PullRequest:
        """Get or create a pull-request row, updating its fields."""
        pr = self.session.scalar(
            select(PullRequest).where(
                PullRequest.repository_id == repo.id, PullRequest.number == number
            )
        )
        if pr is None:
            pr = PullRequest(id=new_id("PR"), repository_id=repo.id, number=number)
            self.session.add(pr)
        for key, value in fields.items():
            if value is not None:
                setattr(pr, key, value)
        pr.updated_at = utcnow()
        self.session.flush()
        return pr

    # ------------------------------------------------------------------ reviews
    def create_review(
        self,
        repo: Repository,
        *,
        request: dict[str, Any],
        source: str,
        title: str | None = None,
        pull_request: PullRequest | None = None,
        review_id: str | None = None,
    ) -> Review:
        """Insert a queued review."""
        review = Review(
            id=review_id or new_id("R"),
            repository_id=repo.id,
            pull_request_id=pull_request.id if pull_request else None,
            status=ReviewStatus.QUEUED.value,
            source=source,
            title=title,
            request=request,
            stages=[],
            errors=[],
        )
        self.session.add(review)
        self.session.flush()
        return review

    def list_reviews(
        self, user: User, limit: int = 50, repo_id: str | None = None
    ) -> Sequence[Review]:
        """The user's reviews, newest first (all reviews for admins)."""
        stmt = select(Review).join(Repository).order_by(Review.created_at.desc()).limit(limit)
        if not user.is_admin:
            stmt = stmt.where(Repository.owner_id == user.id)
        if repo_id:
            stmt = stmt.where(Review.repository_id == repo_id)
        return self.session.scalars(stmt).all()

    def review_for(self, user: User, review_id: str) -> Review | None:
        """The review if ``user`` may see it, else None."""
        review = self.session.get(Review, review_id)
        if review is None or not self.can_access(user, review.repository):
            return None
        return review

    def latest_review(self, user: User) -> Review | None:
        """The user's most recent review."""
        found = self.list_reviews(user, limit=1)
        return found[0] if found else None

    def update_stages(self, review: Review, stages: list[StageRecord]) -> None:
        """Save stage progress (marks a queued review as running)."""
        review.stages = [s.model_dump(mode="json") for s in stages]
        if review.status == ReviewStatus.QUEUED.value:
            review.status = ReviewStatus.RUNNING.value
            review.started_at = review.started_at or utcnow()

    def save_result(self, review: Review, result: ReviewResult) -> None:
        """Store a finished ``ReviewResult``: status, summary, findings, runs, graph, sources."""
        review.status = result.status.value
        review.title = review.title or result.changeset.title
        review.base_ref = result.changeset.base_ref
        review.head_ref = result.changeset.head_ref
        review.risk = result.summary.risk.value
        review.provider = result.provider
        review.model = result.model
        review.input_tokens = result.usage.input_tokens
        review.output_tokens = result.usage.output_tokens
        review.summary = result.summary.model_dump(mode="json")
        review.stages = [s.model_dump(mode="json") for s in result.stages]
        review.changeset = result.changeset.model_dump(mode="json")
        review.sources = dict(result.sources)
        review.errors = list(result.errors)
        review.started_at = review.started_at or result.started_at
        review.finished_at = utcnow()
        review.duration_ms = result.duration_ms
        # replace findings/runs/graph (a re-run of the same review id overwrites)
        for old in list(review.findings):
            self.session.delete(old)
        self.session.flush()
        rows = [
            self._finding_row(review.id, f, rank, suppressed=False)
            for rank, f in enumerate(result.findings)
        ]
        rows += [
            self._finding_row(review.id, f, rank, suppressed=True)
            for rank, f in enumerate(result.suppressed, start=len(result.findings))
        ]
        review.findings = rows
        self.session.execute(delete(AnalysisRunRow).where(AnalysisRunRow.review_id == review.id))
        for run in result.analysis_runs:
            self.session.add(AnalysisRunRow(review_id=review.id, **run.model_dump()))
        if result.graph is not None:
            snap = self.session.get(CodeGraphSnapshot, review.id)
            if snap is None:
                self.session.add(CodeGraphSnapshot(review_id=review.id, graph=result.graph))
            else:
                snap.graph = result.graph
        self.session.flush()

    @staticmethod
    def _finding_row(review_id: str, f: DomainFinding, rank: int, *, suppressed: bool) -> Finding:
        return Finding(
            id=f.id,
            review_id=review_id,
            rank=rank,
            fingerprint=f.fingerprint,
            category=f.category.value,
            severity=f.severity.value,
            confidence=f.confidence,
            title=f.title,
            file=f.file,
            line_start=f.line_start,
            line_end=f.line_end,
            source=f.source.value,
            status=f.status.value,
            verification_status=f.verification.status.value if f.verification else None,
            priority=f.priority.score if f.priority else 0.0,
            suppressed=suppressed,
            suppressed_reason=f.suppressed_reason,
            merged_ids="," + ",".join(f.merged_ids) + "," if f.merged_ids else "",
            data=f.model_dump(mode="json"),
        )

    def mark_failed(self, review: Review, error: str) -> None:
        """Mark a review failed and record why."""
        review.status = ReviewStatus.FAILED.value
        review.errors = [*(review.errors or []), error]
        review.finished_at = utcnow()

    # ------------------------------------------------------------------ rebuild
    @staticmethod
    def domain_finding(row: Finding) -> DomainFinding:
        """Turn a finding row back into a domain ``Finding`` (with its current status)."""
        f = DomainFinding.model_validate(row.data)
        f.status = FindingStatus(row.status)
        return f

    def load_result(self, review: Review) -> ReviewResult:
        """Rebuild the ``ReviewResult`` of a stored review."""
        findings = [self.domain_finding(r) for r in review.findings if not r.suppressed]
        suppressed = [self.domain_finding(r) for r in review.findings if r.suppressed]
        runs = self.session.scalars(
            select(AnalysisRunRow).where(AnalysisRunRow.review_id == review.id)
        ).all()
        snap = self.session.get(CodeGraphSnapshot, review.id)
        return ReviewResult(
            review_id=review.id,
            status=ReviewStatus(review.status),
            changeset=ChangeSet.model_validate(review.changeset or {}),
            findings=findings,
            suppressed=suppressed,
            summary=ReviewSummary.model_validate(review.summary or {}),
            stages=[StageRecord.model_validate(s) for s in review.stages or []],
            analysis_runs=[
                AnalysisRun(
                    tool=r.tool,
                    status=r.status,
                    duration_ms=r.duration_ms,
                    findings=r.findings,
                    detail=r.detail,
                )
                for r in runs
            ],
            errors=list(review.errors or []),
            provider=review.provider,
            model=review.model,
            usage=TokenUsage(input_tokens=review.input_tokens, output_tokens=review.output_tokens),
            graph=snap.graph if snap else None,
            sources=dict(review.sources or {}),
            duration_ms=review.duration_ms or 0,
        )

    def graph(self, review: Review) -> CodeGraph:
        """The review's architecture subgraph (empty if none was stored)."""
        snap = self.session.get(CodeGraphSnapshot, review.id)
        return CodeGraph.from_dict(snap.graph) if snap else CodeGraph()

    # ------------------------------------------------------------------ findings
    def finding_for(self, user: User, finding_id: str) -> Finding | None:
        """The finding (or a finding merged into it) if ``user`` may see it."""
        row = self.session.get(Finding, finding_id)
        if row is None and finding_id:
            # accept ids of findings that were merged into another one
            row = self.session.scalar(
                select(Finding).where(Finding.merged_ids.contains(f",{finding_id},")).limit(1)
            )
        if row is None or not self.can_access(user, row.review.repository):
            return None
        return row

    def set_status(
        self, row: Finding, status: FindingStatus, actor: User | None, note: str | None = None
    ) -> FindingEvent:
        """Change a finding's status and record the change in its history."""
        event = FindingEvent(
            finding_id=row.id,
            actor_id=actor.id if actor else None,
            event="status_changed",
            from_status=row.status,
            to_status=status.value,
            note=note,
        )
        row.status = status.value
        data = dict(row.data)
        data["status"] = status.value
        row.data = data
        self.session.add(event)
        self.session.flush()
        return event

    def record_event(self, row: Finding, event: str, actor: User | None, note: str | None) -> None:
        """Append an entry to a finding's history."""
        self.session.add(
            FindingEvent(
                finding_id=row.id, actor_id=actor.id if actor else None, event=event, note=note
            )
        )
        self.session.flush()

    def events(self, finding_id: str) -> Sequence[FindingEvent]:
        """A finding's history, oldest first."""
        return self.session.scalars(
            select(FindingEvent)
            .where(FindingEvent.finding_id == finding_id)
            .order_by(FindingEvent.id)
        ).all()

    # ------------------------------------------------------------------ fixes
    def create_fix(self, row: Finding) -> FixAttempt:
        """Insert a queued fix attempt for a finding."""
        fix = FixAttempt(id=new_id("X"), finding_id=row.id, status="queued")
        self.session.add(fix)
        self.session.flush()
        return fix

    def fix_for(self, user: User, fix_id: str) -> FixAttempt | None:
        """The fix attempt if ``user`` may see its finding, else None."""
        fix = self.session.get(FixAttempt, fix_id)
        if fix is None:
            return None
        finding = self.session.get(Finding, fix.finding_id)
        if finding is None or not self.can_access(user, finding.review.repository):
            return None
        return fix

    def fixes_for_finding(self, finding_id: str) -> Sequence[FixAttempt]:
        """Fix attempts for a finding, newest first."""
        return self.session.scalars(
            select(FixAttempt)
            .where(FixAttempt.finding_id == finding_id)
            .order_by(FixAttempt.created_at.desc())
        ).all()
