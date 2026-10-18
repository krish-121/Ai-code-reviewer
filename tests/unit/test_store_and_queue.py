"""Database store (tenancy, results, findings) and the job queue (claim, lease, retry)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from sentinel.core.domain.graph import CodeGraph, GraphNode, NodeKind
from sentinel.core.domain.models import (
    AnalysisRun,
    Category,
    ChangeSet,
    Finding,
    FindingSource,
    FindingStatus,
    ReviewResult,
    ReviewStatus,
    Severity,
    StageName,
    StageRecord,
    StageStatus,
    utcnow,
)
from sentinel.infrastructure.database.models import Job
from sentinel.infrastructure.database.session import Database, normalize_url
from sentinel.infrastructure.database.store import Store, hash_token
from sentinel.infrastructure.queue import jobs
from tests.helpers import DATABASE_BACKENDS, fresh_database_url


@pytest.fixture(params=DATABASE_BACKENDS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Database]:
    """An empty database: SQLite, and PostgreSQL when SENTINEL_TEST_DATABASE_URL is set."""
    database = Database(fresh_database_url(request.param, tmp_path))
    database.create_all()
    yield database
    database.engine.dispose()


def _finding(**kw: object) -> Finding:
    base: dict[str, object] = {
        "category": Category.SECURITY,
        "severity": Severity.HIGH,
        "confidence": 0.9,
        "title": "SQL injection",
        "file": "a.py",
        "line_start": 3,
        "line_end": 3,
        "source": FindingSource.AI,
        "origins": ["ai:x"],
        "fingerprint": "abc",
    }
    base.update(kw)
    return Finding(**base)  # type: ignore[arg-type]


def _result() -> ReviewResult:
    g = CodeGraph()
    g.add_node(GraphNode(id="f", kind=NodeKind.FUNCTION, name="f"))
    return ReviewResult(
        changeset=ChangeSet(title="t"),
        status=ReviewStatus.COMPLETED,
        findings=[_finding(merged_ids=["F-old1"])],
        suppressed=[_finding(title="nope", suppressed_reason="rejected")],
        stages=[StageRecord(name=StageName.PARSE_DIFF, status=StageStatus.DONE)],
        analysis_runs=[AnalysisRun(tool="ruff", status="ok", findings=1)],
        graph=g.to_dict(),
        sources={"a.py": "x = 1\n"},
        provider="claude",
        model="m",
    )


def test_database_urls_use_the_psycopg_driver() -> None:
    assert normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("postgresql://h/db") == "postgresql+psycopg://h/db"
    assert normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_file_backed_sqlite(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = Database(f"sqlite:///{tmp_path}/nested/dir/s.db")
    database.create_all()
    assert (tmp_path / "nested" / "dir" / "s.db").exists()
    assert database.dialect == "sqlite"


def test_review_roundtrip_and_status_events(db: Database) -> None:
    with db.transaction() as s:
        store = Store(s)
        user = store.local_user()
        repo = store.repository(user, "demo", local_path="/tmp/demo")
        assert store.repository(user, "demo") is repo  # idempotent
        review = store.create_review(repo, request={"kind": "local"}, source="staged")
        store.update_stages(review, [StageRecord(name=StageName.PARSE_DIFF)])
        assert review.status == "running"
        store.save_result(review, _result())
        rid = review.id
        fid = review.findings[0].id
    with db.transaction() as s:
        store = Store(s)
        user = store.local_user()
        review = store.review_for(user, rid)
        assert review is not None
        loaded = store.load_result(review)
        assert loaded.provider == "claude" and loaded.sources == {"a.py": "x = 1\n"}
        assert [f.title for f in loaded.findings] == ["SQL injection"]
        assert [f.title for f in loaded.suppressed] == ["nope"]
        assert loaded.analysis_runs[0].tool == "ruff"
        assert len(store.graph(review)) == 1
        # merged ids resolve to the surviving finding
        row = store.finding_for(user, "F-old1")
        assert row is not None and row.id == fid
        event = store.set_status(row, FindingStatus.DISMISSED, user, "false positive")
        assert (event.from_status, event.to_status) == ("open", "dismissed")
        assert store.domain_finding(row).status is FindingStatus.DISMISSED
        store.record_event(row, "fix_generated", None, "X-1")
        assert [e.event for e in store.events(row.id)] == ["status_changed", "fix_generated"]
        fix = store.create_fix(row)
        assert store.fix_for(user, fix.id) is fix
        assert list(store.fixes_for_finding(row.id)) == [fix]
        # re-saving replaces findings rather than duplicating them
        store.save_result(review, _result())
        assert len(review.findings) == 2
        store.mark_failed(review, "boom")
        assert review.status == "failed" and "boom" in review.errors


def test_tenant_isolation(db: Database) -> None:
    with db.transaction() as s:
        store = Store(s)
        alice, alice_token = store.create_user("alice")
        bob, _ = store.create_user("bob")
        admin, _ = store.create_user("root", is_admin=True)
        repo = store.repository(alice, "alice/app")
        review = store.create_review(repo, request={}, source="staged")
        store.save_result(review, _result())
        rid, fid = review.id, review.findings[0].id
        fix = store.create_fix(review.findings[0])
        assert store.user_by_token(alice_token) is alice
        assert store.user_by_token("wrong") is None
        assert store.user_by_token("") is None
        assert alice.token_hash == hash_token(alice_token)
        # bob can't see alice's data by any route
        assert store.review_for(bob, rid) is None
        assert store.finding_for(bob, fid) is None
        assert store.fix_for(bob, fix.id) is None
        assert store.list_reviews(bob) == []
        assert store.fix_for(bob, "X-missing") is None
        # alice and admins can
        assert store.review_for(alice, rid) is not None
        assert store.review_for(admin, rid) is not None
        assert [r.id for r in store.list_reviews(alice, repo_id=repo.id)] == [rid]


def test_installations_and_pull_requests(db: Database) -> None:
    with db.transaction() as s:
        store = Store(s)
        alice, _ = store.create_user("alice")
        assert store.installation_owner(None).id == "system-github"
        assert store.installation_owner(42).id == "system-github"
        store.link_installation(42, alice, "acme")
        assert store.installation_owner(42) is alice
        store.link_installation(42, alice, None)
        repo = store.repository(alice, "acme/app", kind="github", installation_id=42)
        pr = store.pull_request(repo, 7, title="Add X", head_sha="abc")
        again = store.pull_request(repo, 7, head_sha="def", title=None)
        assert again is pr and pr.head_sha == "def" and pr.title == "Add X"


# ----------------------------------------------------------------- job queue


def test_queue_claim_complete_and_ordering(db: Database) -> None:
    with db.session() as s:
        first = jobs.enqueue(s, "review", {"n": 1})
        jobs.enqueue(s, "review", {"n": 2})
        jobs.enqueue(s, "fix", {"n": 3}, delay_s=3600)  # not runnable yet
        s.commit()
        assert jobs.pending(s) == 3
        job = jobs.claim(s, "w1")
        assert job is not None and job.id == first.id and job.status == "running"
        assert job.attempts == 1 and job.worker_id == "w1"
        assert jobs.heartbeat(s, job.id, "w1", attempt=job.attempts)
        assert not jobs.heartbeat(s, job.id, "someone-else", attempt=job.attempts)
        jobs.complete(s, job)
        second = jobs.claim(s, "w1", kinds=["review"])
        assert second is not None and second.payload == {"n": 2}
        assert jobs.claim(s, "w1") is None  # the fix job is delayed
        assert jobs.claim(s, "w2", kinds=["publish"]) is None


def test_queue_retry_and_final_failure(db: Database) -> None:
    with db.session() as s:
        jobs.enqueue(s, "review", {}, max_attempts=2)
        s.commit()
        job = jobs.claim(s, "w")
        assert job is not None
        jobs.fail(s, job, "boom")
        assert job.status == "queued" and job.run_after > utcnow()
        s.execute(update(Job).values(run_after=utcnow() - timedelta(seconds=1)))
        s.commit()
        job = jobs.claim(s, "w")
        assert job is not None and job.attempts == 2
        jobs.fail(s, job, "boom again")
        assert job.status == "failed" and job.last_error == "boom again"
        jobs.enqueue(s, "review", {})
        s.commit()
        j3 = jobs.claim(s, "w")
        assert j3 is not None
        jobs.fail(s, j3, "config error", retry=False)
        assert j3.status == "failed"


def test_crashed_worker_lease_expires_and_job_is_reclaimed(db: Database) -> None:
    with db.session() as s:
        jobs.enqueue(s, "review", {"id": "R-1"})
        s.commit()
        job = jobs.claim(s, "crashy", lease_s=60)
        assert job is not None
        assert jobs.claim(s, "healthy") is None  # still leased
        s.execute(update(Job).values(lease_until=utcnow() - timedelta(seconds=1)))
        s.commit()
        recovered = jobs.claim(s, "healthy")
        assert recovered is not None and recovered.id == job.id
        assert recovered.worker_id == "healthy" and recovered.attempts == 2


def test_concurrent_workers_never_claim_the_same_job(db: Database) -> None:
    # Arrange: more jobs than workers, so every worker claims several times.
    with db.session() as s:
        for n in range(24):
            jobs.enqueue(s, "review", {"n": n})
        s.commit()
    claimed: list[str] = []
    lock = threading.Lock()

    def work(worker: str) -> None:
        while True:
            with db.session() as s:
                job = jobs.claim(s, worker)
                if job is None:
                    return
                with lock:
                    claimed.append(job.id)
                jobs.complete(s, job)

    # Act: four workers race for the same queue.
    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Assert: every job ran exactly once.
    assert len(claimed) == 24
    assert len(set(claimed)) == 24
