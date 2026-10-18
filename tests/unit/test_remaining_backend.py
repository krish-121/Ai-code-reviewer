"""Regressions for audit S10–S15: identity, snapshot consistency and job ownership."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, update

from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import utcnow
from sentinel.infrastructure.database.models import Job, Review
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.queue import jobs
from sentinel.infrastructure.queue.fencing import LeaseLostError, owned
from sentinel.integrations.github.client import GitHubAppAuth, GitHubClient, StaticToken
from sentinel.integrations.github.snapshots import SupersededReviewError, require_revision
from sentinel.integrations.github.webhooks import parse_pull_request_event
from sentinel.services.reviews import ReviewService
from sentinel.services.workspaces import LocalRequest, prepare_local
from tests.helpers import DATABASE_BACKENDS, fresh_database_url
from tests.unit.test_github import DIFF, FakeGitHub, _finding, _result, pr_payload


@pytest.fixture(params=DATABASE_BACKENDS)
def db(tmp_path: Path, request: pytest.FixtureRequest):
    database = Database(fresh_database_url(request.param, tmp_path))
    database.create_all()
    yield database
    database.engine.dispose()


def test_s10_same_basename_keeps_distinct_review_roots(db: Database, tmp_path: Path) -> None:
    service = ReviewService(db, Settings(provider="none"))
    ids = []
    for parent in ("first", "second"):
        path = tmp_path / parent / "app"
        path.mkdir(parents=True)
        ids.append(service.create_local("local", LocalRequest(path=str(path)), enqueue=False))
    with db.session() as session:
        first, second = [session.get_one(Review, rid) for rid in ids]
        assert first.repository_id != second.repository_id
        assert first.request["path"] == str((tmp_path / "first/app").resolve())
        assert first.repository.local_path == first.request["path"]


@pytest.mark.skipif(os.name != "posix", reason="confined fix application requires POSIX")
def test_s10_apply_ignores_mutable_repository_path(db: Database, tmp_path: Path) -> None:
    from sentinel.core.domain.ai import FileEdit
    from sentinel.core.domain.models import ChangeSet, ReviewResult
    from sentinel.core.fixes.engine import FixOutcome
    from sentinel.core.fixes.patch import sha256
    from sentinel.infrastructure.database.store import Store
    from sentinel.services.fixes import FixService

    original, other = tmp_path / "original", tmp_path / "other"
    for root in (original, other):
        root.mkdir()
        (root / "a.py").write_text("value = 1\n")
    settings = Settings(provider="none")
    service = ReviewService(db, settings)
    rid = service.create_local(
        "local", LocalRequest(path=str(original), mode="path"), enqueue=False
    )
    with db.transaction() as session:
        store = Store(session)
        review = session.get_one(Review, rid)
        store.save_result(
            review,
            ReviewResult(
                changeset=ChangeSet(), findings=[_finding(file="a.py", line_start=1, line_end=1)]
            ),
        )
        fix_id = store.create_fix(review.findings[0]).id
        review.repository.local_path = str(other)
    fixes = FixService(db, settings)
    fixes.save_outcome(
        fix_id,
        FixOutcome(
            status="validated",
            edits=[FileEdit(file="a.py", search="1", replace="2")],
            original_hashes={"a.py": sha256("value = 1\n")},
        ),
    )
    assert fixes.apply(fix_id) == ["a.py"]
    assert (original / "a.py").read_text() == "value = 2\n"
    assert (other / "a.py").read_text() == "value = 1\n"


def test_s12_stale_claim_cannot_finish_fail_heartbeat_or_write(db: Database) -> None:
    with db.session() as session:
        jobs.enqueue(session, "review", {})
        session.commit()
        stale = jobs.claim(session, "same-worker")
        assert stale is not None
        session.expunge(stale)
        session.execute(update(Job).values(lease_until=utcnow() - timedelta(seconds=1)))
        session.commit()
        fresh = jobs.claim(session, "same-worker")
        assert fresh is not None and fresh.attempts == 2
        assert not jobs.heartbeat(session, stale.id, "same-worker", attempt=stale.attempts)
        assert not jobs.complete(session, stale)
        assert not jobs.fail(session, stale, "old error")
    with owned(stale), pytest.raises(LeaseLostError), db.transaction():
        pytest.fail("stale worker entered a service transaction")
    with db.session() as session:
        row = session.get_one(Job, stale.id)
        assert row.status == "running" and row.attempts == 2 and row.last_error is None


def test_s12_crashes_exhaust_retry_budget(db: Database) -> None:
    with db.session() as session:
        jobs.enqueue(session, "review", {}, max_attempts=1)
        session.commit()
        job = jobs.claim(session, "crashed")
        assert job is not None
        session.execute(update(Job).values(lease_until=utcnow() - timedelta(seconds=1)))
        session.commit()
        assert jobs.claim(session, "recovery") is None
        session.refresh(job)
        assert job.status == "failed" and job.attempts == 1


def test_s13_concurrent_redeliveries_queue_one_review(db: Database) -> None:
    service = ReviewService(db, Settings(provider="none"))
    event = parse_pull_request_event("pull_request", pr_payload())
    assert event is not None
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda n: service.create_github(event, delivery_id=str(n)), range(8)))
    assert len(set(ids)) == 1
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        assert session.scalar(select(func.count()).select_from(Review)) == 1


@pytest.mark.parametrize("side", ["head", "base"])
def test_s11_changed_pr_revision_is_rejected(side: str) -> None:
    pr = pr_payload()["pull_request"]
    pr[side]["sha"] = "new"
    client = GitHubClient(
        StaticToken("test"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=pr))
    )
    with pytest.raises(SupersededReviewError):
        require_revision(client, "acme/shop", 7, "h" * 40, "b" * 40)


def test_s14_foreign_and_unattributed_markers_are_not_owned() -> None:
    client = GitHubClient(
        StaticToken("test"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": 42})),
    )
    assert client.owns_comment("acme/shop", {"user": {"id": 42}})
    assert not client.owns_comment("acme/shop", {"user": {"id": 43}})
    assert not client.owns_comment("acme/shop", {"body": "<!-- sentinel:summary -->"})


def test_s14_app_bot_identity_comes_from_authenticated_app(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app":
            assert request.headers["authorization"] == "Bearer signed-app-jwt"
            return httpx.Response(200, json={"slug": "sentinel"})
        if request.url.path == "/users/sentinel[bot]":
            return httpx.Response(200, json={"id": 123, "type": "Bot"})
        return httpx.Response(201, json={"token": "installation-token"})

    transport = httpx.MockTransport(respond)
    auth = GitHubAppAuth("42", "unused", 7, transport=transport)
    monkeypatch.setattr(auth, "app_jwt", lambda: "signed-app-jwt")
    client = GitHubClient(auth, transport=transport)
    assert client.owns_comment("acme/shop", {"user": {"id": 123, "type": "Bot"}})
    assert not client.owns_comment("acme/shop", {"user": {"id": 124, "type": "Bot"}})
    assert not client.owns_comment("acme/shop", {"user": {"id": 123, "type": "User"}})


def test_s14_foreign_markers_cannot_suppress_or_redirect_publication() -> None:
    from sentinel.analysis.diff.parser import parse_unified_diff
    from sentinel.integrations.github.publisher import GitHubPublisher

    github = FakeGitHub()
    finding = _finding()
    github.issue_comments.append(
        {"id": 999, "user": {"id": 99}, "body": "<!-- sentinel:summary -->"}
    )
    github.review_comments.append(
        {"user": {"id": 99}, "body": f"<!-- sentinel:fp={finding.fingerprint} -->"}
    )
    published = GitHubPublisher(github.client()).publish(
        "acme/shop", 7, "h" * 40, _result(finding), parse_unified_diff(DIFF)
    )
    assert published.posted == [finding.id] and not published.summary_updated
    assert github.issue_comments[0]["body"] == "<!-- sentinel:summary -->"
    assert published.summary_comment_id != 999


def test_s11_push_between_metadata_and_diff_prevents_analysis(db: Database) -> None:
    class MovingGitHub(FakeGitHub):
        moved = False

        def _pull(self, request: httpx.Request) -> httpx.Response:
            if "diff" in request.headers.get("accept", ""):
                self.moved = True
                return httpx.Response(200, text=DIFF)
            data = pr_payload()["pull_request"]
            if self.moved:
                data["head"]["sha"] = "new-head"
            return httpx.Response(200, json=data)

    github = MovingGitHub()
    service = ReviewService(db, Settings(provider="none"), github_factory=lambda _: github.client())
    event = parse_pull_request_event("pull_request", pr_payload())
    assert event is not None
    review_id = service.create_github(event, enqueue=False)
    with pytest.raises(SupersededReviewError):
        service.run(review_id)
    assert not any("tarball" in request.url.path for request in github.requests)


@pytest.mark.parametrize("mode", ["staged", "range"])
def test_s15_context_comes_from_requested_tree(tmp_path: Path, mode: str) -> None:
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    helper = tmp_path / "helper.py"
    helper.write_text("value = 'committed'\n")
    git("add", ".")
    git("commit", "-m", "base")
    (tmp_path / "main.py").write_text("import helper\n")
    git("add", ".")
    if mode == "range":
        git("commit", "-m", "head")
        helper.write_text("value = 'staged'\n")
        git("add", ".")
    else:
        helper.write_text("value = 'unstaged'\n")
    with prepare_local(LocalRequest(path=str(tmp_path), mode=mode)) as workspace:
        assert (workspace.workspace / "helper.py").read_text() == "value = 'committed'\n"
