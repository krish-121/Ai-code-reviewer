"""Persisted findings and allowed-root regressions at the actual HTTP boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sentinel.core.domain.models import ChangeSet, ReviewResult, VerificationResult
from sentinel.infrastructure.database.store import Store
from tests.integration.test_api import H, make
from tests.unit.test_fix_engine import sqli_finding


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py", ".env", "a.py"])
def test_s01_s03_persisted_rejected_findings_cannot_queue_fixes(tmp_path: Path, path: str) -> None:
    client, db, worker, ai = make(tmp_path)
    bad = sqli_finding().model_copy(
        update={
            "file": path,
            "fingerprint": "rejected-location",
            "verification": VerificationResult(status="rejected", score=-1),
        }
    )
    with db.transaction() as session:
        store = Store(session)
        repo = store.repository(store.local_user(), "app", local_path=str(tmp_path))
        review = store.create_review(repo, request={"kind": "local"}, source="path")
        store.save_result(review, ReviewResult(changeset=ChangeSet(), suppressed=[bad]))
        fid = review.findings[0].id
    response = client.post(f"/api/findings/{fid}/fix", headers=H)
    assert response.status_code == 422
    assert not worker.run_once() and not ai.fix_requests


def test_s05_api_rejects_allowed_child_of_disallowed_git_root(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    child = tmp_path / "allowed"
    child.mkdir()
    client, _db, worker, _ai = make(child)
    response = client.post("/api/reviews", headers=H, json={"path": str(child), "mode": "path"})
    assert response.status_code == 403 and "effective repository root" in response.text
    assert not worker.run_once()


def test_s04_ignored_caller_never_enters_provider_or_saved_sources(tmp_path: Path) -> None:
    from sentinel.analysis.diff.git import path_changeset
    from sentinel.bootstrap import build_orchestrator
    from sentinel.core.configuration.config import RepoConfig, Settings
    from tests.fakes import ScriptedProvider

    (tmp_path / "main.py").write_text("def changed(value):\n    return value\n")
    (tmp_path / "private").mkdir()
    marker = "NEVER_SEND_THIS_IGNORED_CALLER"
    (tmp_path / "private" / "caller.py").write_text(
        f"from main import changed\ndef invoke():\n    return changed('{marker}')\n"
    )
    ai = ScriptedProvider()
    config = RepoConfig(ignore=["private/"])
    runner = build_orchestrator(Settings(), config, workspace=tmp_path, ai=ai)
    result = runner.review(path_changeset(tmp_path), tmp_path)
    assert ai.requests and marker not in ai.requests[0].model_dump_json()
    assert "private/caller.py" not in result.sources
    assert marker not in str(result.sources)


def test_s06_tool_failure_makes_review_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sentinel.analysis.static.python_tools as tools
    from sentinel.analysis.diff.git import path_changeset
    from sentinel.analysis.static.base import ToolResult
    from sentinel.bootstrap import build_orchestrator
    from sentinel.core.configuration.config import RepoConfig, Settings

    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(tools, "find_tool", lambda *_args, **_kwargs: "tool")
    monkeypatch.setattr(
        tools, "run_tool", lambda *_args, **_kwargs: ToolResult(2, "", "configuration error", 1)
    )
    runner = build_orchestrator(Settings(), RepoConfig(), workspace=tmp_path, ai=None)
    result = runner.review(path_changeset(tmp_path), tmp_path)
    assert result.status == "partial"
    assert any(run.tool == "ruff" and run.status == "failed" for run in result.analysis_runs)
