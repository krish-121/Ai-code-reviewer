"""Background worker: claims jobs from the database queue and runs them."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections.abc import Callable

from sentinel.infrastructure.database.models import Job
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.observability.logging import review_id_var
from sentinel.infrastructure.observability.metrics import METRICS
from sentinel.infrastructure.queue import jobs
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService

log = logging.getLogger("sentinel.worker")


class Worker:
    def __init__(
        self,
        db: Database,
        reviews: ReviewService,
        fixes: FixService,
        *,
        worker_id: str | None = None,
        poll_s: float = 1.0,
        lease_s: int = 300,
    ) -> None:
        self.db = db
        self.reviews = reviews
        self.fixes = fixes
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.poll_s = poll_s
        self.lease_s = lease_s
        self.handlers: dict[str, Callable[[Job], None]] = {
            "review": self._review,
            "publish": self._publish,
            "fix": self._fix,
        }

    def _review(self, job: Job) -> None:
        review_id = str(job.payload["review_id"])
        token = review_id_var.set(review_id)
        try:
            result = self.reviews.run(review_id)
            METRICS.record_review(result)
        finally:
            review_id_var.reset(token)

    def _publish(self, job: Job) -> None:
        self.reviews.publish(str(job.payload["review_id"]))

    def _fix(self, job: Job) -> None:
        start = time.monotonic()
        outcome = self.fixes.run(str(job.payload["fix_id"]))
        METRICS.record_fix(outcome.status, (time.monotonic() - start) * 1000)

    def run_once(self) -> bool:
        """Claim and run one job. Returns False when the queue was empty."""
        with self.db.session() as s:
            job = jobs.claim(s, self.worker_id, kinds=list(self.handlers), lease_s=self.lease_s)
            if job is None:
                return False
            s.expunge(job)
        stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job.id, stop), daemon=True)
        beat.start()
        log.info("job started", extra={"job": job.id, "kind": job.kind, "attempt": job.attempts})
        start = time.monotonic()
        try:
            self.handlers[job.kind](job)
        except Exception as exc:
            stop.set()
            log.exception("job failed", extra={"job": job.id, "kind": job.kind})
            with self.db.session() as s:
                row = s.get_one(Job, job.id)
                jobs.fail(s, row, f"{type(exc).__name__}: {exc}")
            return True
        stop.set()
        with self.db.session() as s:
            jobs.complete(s, s.get_one(Job, job.id))
        log.info(
            "job done",
            extra={
                "job": job.id,
                "kind": job.kind,
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
        )
        return True

    def _heartbeat(self, job_id: str, stop: threading.Event) -> None:
        interval = max(5.0, self.lease_s / 3)
        while not stop.wait(interval):
            with self.db.session() as s:
                jobs.heartbeat(s, job_id, self.worker_id, self.lease_s)

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        log.info("worker started", extra={"worker": self.worker_id})
        while not stop.is_set():
            try:
                busy = self.run_once()
            except Exception:  # database hiccup: back off, keep the worker alive
                log.exception("worker loop error")
                busy = False
            if not busy:
                stop.wait(self.poll_s)
