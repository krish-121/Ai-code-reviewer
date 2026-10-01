"""HTTP API: review lifecycle, fixes, tenancy, host checks and the web UI fallback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel.apps.api.app import create_app
from sentinel.apps.worker.main import Worker
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import Category, FindingSource, Severity
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService
from tests.fakes import ScriptedProvider
from tests.helpers import DATABASE_BACKENDS, fresh_database_url
from tests.unit.test_fix_engine import FIXED, VULN, fix_payload

DEMO_BUILDER = Path(__file__).resolve().parents[2] / "demo"
H = {"X-Sentinel-Client": "test"}


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    sys.path.insert(0, str(DEMO_BUILDER))
    try:
        import build_demo_repo

        return build_demo_repo.build(tmp_path / "demo")
    finally:
        sys.path.remove(str(DEMO_BUILDER))


def make(
    tmp_path: Path, backend: str = "sqlite", **kw: object
) -> tuple[TestClient, Database, Worker, ScriptedProvider]:
    settings = Settings(
        database_url=fresh_database_url(backend, tmp_path),
        cache_dir=tmp_path / "c",
        local_roots=str(tmp_path),
        **kw,
    )  # type: ignore[arg-type]
    db = Database(settings.database_url)
    db.create_all()
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
    reviews = ReviewService(db, settings, ai_factory=lambda: None)

    from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
    from sentinel.core.fixes.engine import FixEngine

    def engine_factory(root: Path, trusted: bool) -> FixEngine:
        return FixEngine(
            ai,
            static_runner=StaticAnalysisRunner(default_analyzers(), disabled=["mypy"]),
            sandbox=None,
        )

    fixes = FixService(db, settings, engine_factory=engine_factory)
    worker = Worker(db, reviews, fixes)
    return TestClient(create_app(settings, db=db, reviews=reviews, fixes=fixes)), db, worker, ai


@pytest.mark.parametrize("backend", DATABASE_BACKENDS)
def test_local_review_lifecycle_and_fix_flow(tmp_path: Path, demo: Path, backend: str) -> None:
    client, _db, worker, _ai = make(tmp_path, backend)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/me").json()["id"] == "local"

    # CSRF guard and path allow-list
    assert client.post("/api/reviews", json={"path": str(demo), "mode": "range"}).status_code == 403
    outside = client.post("/api/reviews", json={"path": "/etc", "mode": "path"}, headers=H)
    assert outside.status_code == 403
    missing = client.post(
        "/api/reviews", json={"path": str(tmp_path / "nope"), "mode": "path"}, headers=H
    )
    assert missing.status_code == 400

    created = client.post(
        "/api/reviews",
        json={
            "path": str(demo),
            "mode": "range",
            "base": "main",
            "head": "feature/search-and-reports",
        },
        headers=H,
    )
    assert created.status_code == 202
    rid = created.json()["id"]
    assert worker.run_once()
    review = client.get(f"/api/reviews/{rid}").json()
    assert review["status"] == "completed" and review["can_apply_fixes"]
    assert review["mode"] == "range"
    files = client.get(f"/api/reviews/{rid}/files").json()
    assert {f["path"] for f in files["files"]} >= {"app/db.py", "app/routes.py"}
    assert any(s["path"] == ".env" for s in files["skipped"])

    findings = client.get(f"/api/reviews/{rid}/findings", params={"include_suppressed": False})
    sqli = next(f for f in findings.json() if f["file"] == "app/db.py" and "SQL" in f["title"])

    # status changes are recorded as events
    patched = client.patch(
        f"/api/findings/{sqli['id']}", json={"status": "accepted", "note": "real"}, headers=H
    )
    assert patched.status_code == 200 and patched.json()["status"] == "accepted"
    bad = client.patch(f"/api/findings/{sqli['id']}", json={"status": "bogus"}, headers=H)
    assert bad.status_code == 422

    # generate a fix (job) -> validate -> download patch -> apply
    fix_id = client.post(f"/api/findings/{sqli['id']}/fix", headers=H).json()["id"]
    assert worker.run_once()
    fix = client.get(f"/api/fixes/{fix_id}").json()
    assert fix["status"] == "validated", fix
    assert fix["can_apply"]
    patch = client.get(f"/api/fixes/{fix_id}/patch")
    assert patch.headers["content-type"].startswith("text/x-diff")
    assert '+    query = "SELECT id, name, price FROM products WHERE name LIKE ?' in patch.text
    applied = client.post(f"/api/fixes/{fix_id}/apply", headers=H).json()
    assert applied == {"applied": ["app/db.py"]}
    assert "LIKE ?" in (demo / "app/db.py").read_text()
    again = client.post(f"/api/fixes/{fix_id}/apply", headers=H)
    assert again.status_code == 409
    detail = client.get(f"/api/findings/{sqli['id']}").json()
    assert detail["finding"]["status"] == "fixed"
    assert [e["event"] for e in detail["events"]] == [
        "status_changed",
        "fix_generated",
        "status_changed",
    ]
    assert client.post(f"/api/fixes/{fix_id}/reject", headers=H).json() == {"status": "rejected"}

    assert client.get("/api/findings/F-missing").status_code == 404
    assert client.get("/api/fixes/X-missing").status_code == 404
    assert client.get("/api/reviews/R-missing").status_code == 404
    assert "sentinel_" in client.get("/metrics").text or client.get("/metrics").status_code == 200


@pytest.mark.parametrize("backend", DATABASE_BACKENDS)
def test_token_mode_isolates_tenants(tmp_path: Path, backend: str) -> None:
    client, db, _worker, _ai = make(tmp_path, backend, auth_mode="token")
    from sentinel.core.domain.models import ChangeSet, Finding, ReviewResult

    with db.transaction() as s:
        store = Store(s)
        alice, alice_token = store.create_user("alice")
        _bob, bob_token = store.create_user("bob")
        repo = store.repository(alice, "alice/app")
        review = store.create_review(repo, request={"kind": "local"}, source="staged")
        store.save_result(
            review,
            ReviewResult(
                changeset=ChangeSet(),
                findings=[
                    Finding(
                        category=Category.BUG,
                        severity=Severity.LOW,
                        confidence=0.5,
                        title="t",
                        file="a.py",
                        line_start=1,
                        line_end=1,
                        source=FindingSource.AI,
                        fingerprint="f",
                    )
                ],
                sources={"a.py": "secret code"},
            ),
        )
        rid, fid = review.id, review.findings[0].id

    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", **H}

    assert client.get("/api/reviews").status_code == 401
    assert client.get("/api/reviews", headers=auth("nope")).status_code == 401
    assert [r["id"] for r in client.get("/api/reviews", headers=auth(alice_token)).json()] == [rid]
    assert client.get("/api/reviews", headers=auth(bob_token)).json() == []
    for url in (
        f"/api/reviews/{rid}",
        f"/api/reviews/{rid}/findings",
        f"/api/reviews/{rid}/source?path=a.py",
        f"/api/reviews/{rid}/graph",
        f"/api/findings/{fid}",
    ):
        assert client.get(url, headers=auth(bob_token)).status_code == 404, url
        assert client.get(url, headers=auth(alice_token)).status_code == 200, url
    assert client.post(f"/api/findings/{fid}/fix", headers=auth(bob_token)).status_code == 404
    # token mode never allows reviewing arbitrary server paths unless configured
    settings = Settings(database_url=f"sqlite:///{tmp_path}/t2.db", auth_mode="token")
    assert settings.allowed_roots() == []


def test_local_mode_rejects_foreign_hosts(tmp_path: Path) -> None:
    client, *_ = make(tmp_path)
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_spa_fallback(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html>app</html>")
    (ui / "assets" / "app.js").write_text("console.log(1)")
    settings = Settings(database_url=f"sqlite:///{tmp_path}/spa.db")
    client = TestClient(create_app(settings, static_dir=ui))
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/reviews/R-1/findings").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/../../etc/passwd").text == "<html>app</html>"
    bare = TestClient(
        create_app(
            Settings(database_url=f"sqlite:///{tmp_path}/b.db"), static_dir=tmp_path / "none"
        )
    )
    assert "Sentinel API is running" in bare.get("/").text
