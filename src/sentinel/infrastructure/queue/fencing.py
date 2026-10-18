"""Fence every service transaction against the worker's original lease generation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session

from sentinel.core.domain.models import utcnow
from sentinel.infrastructure.database.models import Job


class LeaseLostError(RuntimeError):
    """A reclaimed or expired job may no longer commit side effects."""


@dataclass(frozen=True)
class Lease:
    """Immutable fencing token; worker names alone are not unique claims."""

    job_id: str
    worker_id: str | None
    attempt: int


current_lease: ContextVar[Lease | None] = ContextVar("job_lease", default=None)


@contextmanager
def owned(job: Job) -> Iterator[None]:
    """Propagate the original claim to synchronous service transactions."""
    token = current_lease.set(Lease(job.id, job.worker_id, job.attempts))
    try:
        yield
    finally:
        current_lease.reset(token)


def guard(session: Session) -> None:
    """Validate ownership and lock the job until the enclosing transaction commits."""
    lease = current_lease.get()
    if lease is None:
        return
    result = session.execute(
        update(Job)
        .where(
            Job.id == lease.job_id,
            Job.worker_id == lease.worker_id,
            Job.attempts == lease.attempt,
            Job.status == "running",
            Job.lease_until > utcnow(),
        )
        .values(updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise LeaseLostError("job lease expired or was reclaimed; discard stale work")
