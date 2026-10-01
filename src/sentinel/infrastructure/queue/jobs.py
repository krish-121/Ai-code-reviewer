"""A durable job queue on the database — no Redis required.

Jobs are rows. A worker *claims* one with a conditional UPDATE (and ``FOR UPDATE SKIP
LOCKED`` on PostgreSQL), which gives it a time-limited lease. While it works it extends
the lease with heartbeats. If the worker crashes, the lease expires and another worker
re-claims the job — so a crash delays a review, it never loses one. Failed jobs retry
with exponential backoff up to ``max_attempts``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from sentinel.core.domain.models import new_id, utcnow
from sentinel.infrastructure.database.models import Job

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

MAX_ERROR_CHARS = 2000
RETRY_BASE_DELAY_S = 5  # first retry after 5 s, then 10, 20 ... capped below
MAX_RETRY_DELAY_S = 300
CLAIM_BATCH = 5  # candidates fetched per claim attempt
DEFAULT_LEASE_S = 300

# Job kinds (``Job.kind``); the worker has one handler per kind.
REVIEW_JOB = "review"
PUBLISH_JOB = "publish"
FIX_JOB = "fix"


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = 3,
    delay_s: float = 0.0,
) -> Job:
    """Add a job; it becomes runnable after ``delay_s`` seconds."""
    job = Job(
        id=new_id("J"),
        kind=kind,
        payload=payload,
        status=QUEUED,
        max_attempts=max_attempts,
        run_after=utcnow() + timedelta(seconds=delay_s),
    )
    session.add(job)
    session.flush()
    return job


def claim(
    session: Session,
    worker_id: str,
    *,
    kinds: list[str] | None = None,
    lease_s: int = DEFAULT_LEASE_S,
) -> Job | None:
    """Atomically take the oldest runnable job (or one whose lease expired)."""
    now = utcnow()
    runnable = or_(
        and_(Job.status == QUEUED, Job.run_after <= now),
        and_(Job.status == RUNNING, Job.lease_until < now),
    )
    stmt = select(Job.id).where(runnable).order_by(Job.created_at).limit(CLAIM_BATCH)
    if kinds:
        stmt = stmt.where(Job.kind.in_(kinds))
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    for job_id in session.scalars(stmt).all():
        result = session.execute(
            update(Job)
            .where(Job.id == job_id, runnable)
            .values(
                status=RUNNING,
                worker_id=worker_id,
                lease_until=now + timedelta(seconds=lease_s),
                attempts=Job.attempts + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) == 1:
            session.commit()
            job = session.get(Job, job_id)
            if job is not None:
                session.refresh(job)
            return job
    session.commit()
    return None


def heartbeat(
    session: Session, job_id: str, worker_id: str, lease_s: int = DEFAULT_LEASE_S
) -> bool:
    """Extend a running job's lease; False if this worker no longer holds it."""
    result = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.worker_id == worker_id, Job.status == RUNNING)
        .values(lease_until=utcnow() + timedelta(seconds=lease_s), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return getattr(result, "rowcount", 0) == 1


def complete(session: Session, job: Job) -> None:
    """Mark a job done."""
    job.status = DONE
    job.lease_until = None
    job.updated_at = utcnow()
    session.commit()


def fail(session: Session, job: Job, error: str, *, retry: bool = True) -> None:
    """Record a failure; requeue with exponential backoff while attempts remain."""
    job.last_error = error[:MAX_ERROR_CHARS]
    job.lease_until = None
    job.updated_at = utcnow()
    if retry and job.attempts < job.max_attempts:
        job.status = QUEUED
        delay = min(MAX_RETRY_DELAY_S, RETRY_BASE_DELAY_S * 2 ** (job.attempts - 1))
        job.run_after = utcnow() + timedelta(seconds=delay)
    else:
        job.status = FAILED
    session.commit()


def pending(session: Session) -> int:
    """Number of queued or running jobs."""
    return len(session.scalars(select(Job.id).where(Job.status.in_([QUEUED, RUNNING]))).all())
