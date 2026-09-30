"""End-to-end: GitHub PR -> webhook -> review job -> analysis -> findings -> database ->
GitHub comments -> API/UI endpoints. GitHub and the AI provider are faked at the HTTP /
port boundary; everything in between is the real system."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sentinel.apps.api.app import create_app
from sentinel.apps.worker.main import Worker
from sentinel.core.configuration.config import Settings
from sentinel.infrastructure.database.session import Database
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService
from tests.fakes import ScriptedProvider, ai_finding
from tests.unit.test_github import FakeGitHub, pr_payload, sign

DEMO_BUILDER = Path(__file__).resolve().parents[2] / "demo"
SECRET = "webhook-secret"


@pytest.fixture(scope="module")
def demo_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    sys.path.insert(0, str(DEMO_BUILDER))
    try:
        import build_demo_repo

        return build_demo_repo.build(tmp_path_factory.mktemp("e2e") / "demo")
    finally:
        sys.path.remove(str(DEMO_BUILDER))


class DemoGitHub(FakeGitHub):
    def __init__(self, repo: Path) -> None:
        tarball = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "archive",
                "--format=tar.gz",
                "--prefix=acme-shop-abc/",
                "feature/search-and-reports",
            ],
            check=True,
            capture_output=True,
        ).stdout
        super().__init__(tarball)
        self.diff = subprocess.run(
            ["git", "-C", str(repo), "diff", "main...feature/search-and-reports"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def __call__(self, req: Any) -> Any:
        import httpx

        if req.url.path == "/repos/acme/shop/pulls/7" and "diff" in req.headers.get("accept", ""):
            self.requests.append(req)
            return httpx.Response(200, text=self.diff)
        return super().__call__(req)


AI = [
    ai_finding(
        category="security",
        severity="high",
        confidence=0.85,
        file="app/routes.py",
        line=43,
        title="Authorization check runs before authentication in admin_export",
        explanation="admin_export() calls is_admin() on a user looked up from the "
        "X-User-Email header before verify_token() authenticates the caller.",
        evidence=["admin_export() calls is_admin()"],
    ),
    ai_finding(
        category="security",
        severity="high",
        confidence=0.7,
        file="app/db.py",
        line=24,
        title="SQL injection in find_user",
        explanation="find_user() builds SQL from the email argument.",
    ),
]


def test_github_pull_request_end_to_end(demo_repo: Path, tmp_path: Path) -> None:
    gh = DemoGitHub(demo_repo)
    settings = Settings(
        provider="none",
        database_url=f"sqlite:///{tmp_path}/e2e.db",
        github_webhook_secret=SECRET,
        cache_dir=tmp_path / "cache",  # type: ignore[arg-type]
    )
    db = Database(settings.database_url)
    db.create_all()
    ai = ScriptedProvider(AI)
    reviews = ReviewService(
        db,
        settings,
        ai_factory=lambda: ai,
        github_factory=lambda _inst: gh.client(),
        public_url="https://sentinel.example",
    )
    fixes = FixService(db, settings)
    worker = Worker(db, reviews, fixes, poll_s=0.01)
    client = TestClient(create_app(settings, db=db, reviews=reviews, fixes=fixes))

    # 1. GitHub delivers the webhook
    body = json.dumps(pr_payload()).encode()
    bad = client.post(
        "/api/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=0"},
    )
    assert bad.status_code == 401
    resp = client.post(
        "/api/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign(SECRET, body)},
    )
    assert resp.status_code == 202
    review_id = resp.json()["review_id"]
    queued_resp = client.get(f"/api/reviews/{review_id}")
    assert queued_resp.status_code == 200, queued_resp.text
    queued = queued_resp.json()
    assert queued["status"] == "queued"
    assert queued["pull_request"]["number"] == 7

    # 2. The worker runs the review job (diff + tarball fetched from "GitHub")
    assert worker.run_once()
    detail = client.get(f"/api/reviews/{review_id}").json()
    assert detail["status"] == "completed", detail["errors"]
    assert detail["risk"] == "high"
    assert [s["status"] for s in detail["stages"]].count("done") == 8
    assert detail["can_apply_fixes"] is False
    assert any(r["tool"] == "sentinel" for r in detail["analysis_runs"])

    findings = client.get(f"/api/reviews/{review_id}/findings").json()
    by_title = {f["title"]: f for f in findings}
    auth = by_title["Authorization check runs before authentication in admin_export"]
    assert auth["verification"]["status"] == "supported"
    assert auth["suppressed"] is False
    fp = by_title["SQL injection in find_user"]
    assert fp["suppressed"] and fp["verification"]["status"] == "rejected"
    titles = " ".join(by_title)
    for expected in (
        "SQL",
        "N+1",
        "never awaited",
        "Blocking call",
        "Stripe",
        ".env",
        "Prompt-injection",
        "O(n²)",
    ):
        assert expected in titles, expected

    # untrusted PR content never reached the model as instructions or secrets
    request = ai.requests[0]
    assert "sk_live_SENTINELFIXTURE00001" not in request.model_dump_json()
    assert "Sup3rS3cret" not in request.model_dump_json()

    graph = client.get(f"/api/reviews/{review_id}/graph").json()
    assert any(n["kind"] == "endpoint" for n in graph["nodes"])
    source = client.get(f"/api/reviews/{review_id}/source", params={"path": "app/db.py"})
    assert "search_products" in source.json()["content"]
    assert (
        client.get(
            f"/api/reviews/{review_id}/source", params={"path": "../../etc/passwd"}
        ).status_code
        == 404
    )
    events = client.get(f"/api/reviews/{review_id}/events").text
    assert "event: done" in events

    # 3. The publish job posts to the PR
    assert worker.run_once()
    assert len(gh.issue_comments) == 1
    assert gh.issue_comments[0]["body"].startswith("<!-- sentinel:summary -->")
    assert "https://sentinel.example/reviews/" in gh.issue_comments[0]["body"]
    posted = gh.reviews[0]["comments"]
    assert any(c["path"] == "app/routes.py" for c in posted)
    assert client.get(f"/api/reviews/{review_id}").json()["published_at"]
    assert not worker.run_once()  # queue drained

    # 4. A new push: the summary is updated, existing comments are not duplicated
    body2 = json.dumps(pr_payload("synchronize")).encode()
    client.post(
        "/api/github/webhook",
        content=body2,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign(SECRET, body2)},
    )
    assert worker.run_once() and worker.run_once()
    assert len(gh.issue_comments) == 1
    assert len(gh.reviews) == 1  # no new review: every finding was already commented

    listing = client.get("/api/reviews").json()
    assert len(listing) == 2 and listing[0]["repository"] == "acme/shop"


def test_webhook_edge_cases(tmp_path: Path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/w.db")
    client = TestClient(create_app(settings))
    assert client.post("/api/github/webhook", content=b"{}").status_code == 503
    settings2 = Settings(database_url=f"sqlite:///{tmp_path}/w2.db", github_webhook_secret=SECRET)  # type: ignore[arg-type]
    client2 = TestClient(create_app(settings2))
    ping = b'{"zen": "hi"}'
    r = client2.post(
        "/api/github/webhook",
        content=ping,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": sign(SECRET, ping)},
    )
    assert r.json() == {"pong": True}
    closed = json.dumps(pr_payload("closed")).encode()
    r = client2.post(
        "/api/github/webhook",
        content=closed,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign(SECRET, closed)},
    )
    assert r.json() == {"ignored": True}
    junk = b"not json"
    r = client2.post(
        "/api/github/webhook",
        content=junk,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign(SECRET, junk)},
    )
    assert r.status_code == 400
