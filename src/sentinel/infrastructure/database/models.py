"""Persistence schema (SQLAlchemy 2.0).

PostgreSQL in deployment, SQLite for the local CLI and tests. The database exists
because review history, finding status changes, fix attempts and the job queue must
survive process restarts — not because "real apps use Postgres".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Dialect,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from sentinel.core.domain.models import utcnow


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite stores naive UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _now() -> datetime:
    return utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    github_login: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner_id", "full_name", name="uq_repo_owner_name"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="local")  # local | github
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class GithubInstallation(Base):
    """Maps a GitHub App installation to the Sentinel user that owns its repositories."""

    __tablename__ = "github_installations"

    installation_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repository_id", "number", name="uq_pr_repo_number"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="open")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    pull_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    source: Mapped[str] = mapped_column(String(20), default="local")
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    head_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(10), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stages: Mapped[list[Any]] = mapped_column(JSON, default=list)
    changeset: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sources: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    repository: Mapped[Repository] = relationship()
    pull_request: Mapped[PullRequest | None] = relationship()
    findings: Mapped[list[Finding]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="Finding.rank"
    )


class CodeGraphSnapshot(Base):
    __tablename__ = "code_graph_snapshots"

    review_id: Mapped[str] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True
    )
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_fingerprint", "fingerprint"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(Text)
    file: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    verification_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    suppressed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_ids: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    review: Mapped[Review] = relationship(back_populates="findings")


class FindingEvent(Base):
    __tablename__ = "finding_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    findings: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")


class FixAttempt(Base):
    __tablename__ = "fix_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    edits: Mapped[list[Any]] = mapped_column(JSON, default=list)
    checks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    original_hashes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    isolation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
