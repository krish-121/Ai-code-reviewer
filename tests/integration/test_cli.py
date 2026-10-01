"""The sentinel CLI end to end on a temporary git repository."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sentinel.apps.cli.main import app
from tests.unit.test_fix_engine import FIXED, VULN, fix_payload

DEMO_BUILDER = Path(__file__).resolve().parents[2] / "demo"
runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in list(os.environ):
        if key.startswith("SENTINEL_") or key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SENTINEL_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    monkeypatch.setenv("SENTINEL_CACHE_DIR", str(tmp_path / "cache"))
    sys.path.insert(0, str(DEMO_BUILDER))
    try:
        import build_demo_repo

        repo = build_demo_repo.build(tmp_path / "demo")
    finally:
        sys.path.remove(str(DEMO_BUILDER))
    monkeypatch.chdir(repo)
    return repo


def test_review_range_rich_output(env: Path) -> None:
    res = runner.invoke(
        app,
        [
            "review",
            "--range",
            "main..feature/search-and-reports",
            "--no-ai",
            "--details",
            "--show-suppressed",
        ],
    )
    assert res.exit_code == 0, res.output
    out = res.output
    assert "RISK: HIGH" in out
    assert "search_products" in out
    assert "Reachable from" in out
    assert "deterministic-rule" in out  # --details shows verification checks
    assert "[REDACTED:stripe-key]" in out  # secrets never printed


def test_review_formats_and_fail_on(env: Path) -> None:
    res = runner.invoke(
        app,
        [
            "review",
            "--range",
            "main..feature/search-and-reports",
            "--no-ai",
            "--format",
            "json",
            "--fail-on",
            "high",
        ],
    )
    assert res.exit_code == 1  # high findings present
    data = json.loads(res.stdout)
    assert data["status"] == "completed" and data["summary"]["risk"] == "high"
    assert "sources" not in data
    md = runner.invoke(
        app,
        [
            "review",
            "--range",
            "main..feature/search-and-reports",
            "--no-ai",
            "--format",
            "markdown",
        ],
    )
    assert md.exit_code == 0 and md.stdout.startswith("<!-- sentinel:summary -->")


def test_staged_worktree_and_path_modes(env: Path) -> None:
    (env / "app" / "extra.py").write_text(
        "import os\n\ndef run(cmd):\n    os.system('ls ' + cmd)\n"
    )
    wt = runner.invoke(app, ["review", "--worktree", "--no-ai", "--format", "json"])
    assert wt.exit_code == 0, wt.output
    assert json.loads(wt.stdout)["changeset"]["files"] == []  # untracked files aren't in git diff
    subprocess.run(["git", "add", "app/extra.py"], cwd=env, check=True)
    staged = runner.invoke(app, ["review", "--no-ai", "--format", "json"])  # auto: staged
    titles = [f["title"] for f in json.loads(staged.stdout)["findings"]]
    assert any("Shell command" in t or "shell" in t.lower() for t in titles), titles
    path = runner.invoke(app, ["review", "app", "--no-ai", "--format", "json"])
    data = json.loads(path.stdout)
    assert data["changeset"]["source"] == "path"
    assert {f["path"] for f in data["changeset"]["files"]} >= {"app/db.py", "app/extra.py"}


def test_history_findings_show_and_triage(env: Path) -> None:
    runner.invoke(
        app,
        ["review", "--range", "main..feature/search-and-reports", "--no-ai", "--format", "json"],
    )
    listing = runner.invoke(app, ["reviews"])
    assert listing.exit_code == 0 and "R-" in listing.output
    found = runner.invoke(app, ["findings", "--all"])
    assert found.exit_code == 0 and "feature/search-and-reports" in found.output
    fid = next(tok for tok in found.output.split() if tok.startswith("F-"))
    shown = runner.invoke(app, ["show", fid])
    assert shown.exit_code == 0 and "Verification" in shown.output
    assert runner.invoke(app, ["dismiss", fid, "--note", "fp"]).exit_code == 0
    assert runner.invoke(app, ["accept", fid]).exit_code == 0
    assert "accepted" in runner.invoke(app, ["findings"]).output
    assert runner.invoke(app, ["show", "F-nope"]).exit_code == 1
    assert runner.invoke(app, ["dismiss", "F-nope"]).exit_code == 1


def test_fix_command_with_scripted_provider(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fakes import ScriptedProvider

    runner.invoke(
        app,
        ["review", "--range", "main..feature/search-and-reports", "--no-ai", "--format", "json"],
    )
    found = runner.invoke(app, ["findings"]).output
    line = next(ln for ln in found.splitlines() if "app/db.py" in ln)
    fid = next(tok for tok in line.split() if tok.startswith("F-"))
    import sentinel.bootstrap as bootstrap

    real = bootstrap.build_fix_engine

    def fake_engine(settings, repo_config, **kw):  # type: ignore[no-untyped-def]
        kw["ai"] = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
        kw["sandbox"] = None
        return real(settings, repo_config, **kw)

    monkeypatch.setattr("sentinel.apps.cli.fix_command.build_fix_engine", fake_engine)
    res = runner.invoke(app, ["fix", fid, "--apply", "--yes"])
    assert res.exit_code == 0, res.output
    assert "Patch validated" in res.output and "Applied to app/db.py" in res.output
    assert "LIKE ?" in (env / "app" / "db.py").read_text()
    assert "fixed" in runner.invoke(app, ["findings"]).output
    assert runner.invoke(app, ["fix"]).exit_code == 2


def test_missing_api_key_message(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_PROVIDER", "claude")
    res = runner.invoke(app, ["review", "--range", "main..feature/search-and-reports"])
    assert res.exit_code == 2
    assert "Claude API key not configured" in res.output
    assert "SENTINEL_CLAUDE_KEY" in res.output
    bad = runner.invoke(app, ["review", "--provider", "gpt5"])
    assert bad.exit_code == 2 and "unknown provider" in bad.output


def test_config_set_masks_secrets_and_rejects_unknown_keys(env: Path) -> None:
    assert runner.invoke(app, ["config", "set", "provider", "gemini"]).exit_code == 0
    secret = runner.invoke(app, ["config", "set", "gemini_api_key", "g-123"])
    assert secret.exit_code == 0 and "g-123" not in secret.output
    shown = runner.invoke(app, ["config"])
    assert "gemini" in shown.output and "g-123" not in shown.output and "set" in shown.output
    assert runner.invoke(app, ["config", "set", "nope", "x"]).exit_code == 2
    assert runner.invoke(app, ["config", "init"]).exit_code == 2  # demo has .sentinel.yml
    assert runner.invoke(app, ["config", "init", "--force"]).exit_code == 0
    assert "include_style" in (env / ".sentinel.yml").read_text()


def test_version_graph_and_user_admin_commands(env: Path) -> None:
    assert "sentinel 0.1.0" in runner.invoke(app, ["--version"]).output
    graph = runner.invoke(app, ["graph", ".", "--symbol", "search_products"])
    assert graph.exit_code == 0 and "callers: search" in graph.output
    user = runner.invoke(app, ["users", "create", "alice"])
    assert user.exit_code == 0 and "snt_" in user.output
    uid = next(tok for tok in user.output.split() if tok.startswith("U-"))
    assert runner.invoke(app, ["users", "link-installation", "5", uid]).exit_code == 0
    assert runner.invoke(app, ["users", "link-installation", "5", "U-none"]).exit_code == 1
    assert runner.invoke(app, ["serve", "--host", "0.0.0.0"]).exit_code == 2  # noqa: S104
    assert runner.invoke(app, ["review", "--pr", "3"]).exit_code == 2  # no GitHub token


def test_not_a_git_repo(tmp_path: Path, env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    res = runner.invoke(app, ["review", "--staged"])
    assert res.exit_code == 2 and "not inside a git repository" in res.output
