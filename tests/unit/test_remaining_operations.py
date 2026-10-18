"""Operational regressions: shared metrics, bounded output, CLI contracts and resources."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sentinel.apps.cli.main import app
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import ChangeSet, ReviewResult
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.infrastructure.observability.durable import render_persisted
from sentinel.infrastructure.observability.metrics import BUCKETS_MS, Metrics
from sentinel.sandbox.output import MAX_CAPTURE_BYTES, communicate_capped
from sentinel.services.resources import close_provider
from tests.unit.test_github import FakeGitHub


def test_s26_metrics_are_visible_to_a_separate_database_reader(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/metrics.db"
    writer = Database(url)
    writer.create_all()
    with writer.transaction() as session:
        store = Store(session)
        repo = store.repository(store.local_user(), "metrics")
        review = store.create_review(repo, request={}, source="path")
        store.save_result(review, ReviewResult(changeset=ChangeSet(), duration_ms=123))
    writer.engine.dispose()
    reader = Database(url)
    try:
        with reader.session() as session:
            text = render_persisted(session)
        assert 'sentinel_reviews_total{status="completed"} 1' in text
        assert "sentinel_review_duration_ms_sum 123" in text
    finally:
        reader.engine.dispose()


def test_s26_histogram_memory_does_not_grow_with_measurements() -> None:
    metrics = Metrics()
    for _ in range(100_000):
        metrics.observe("latency", 42)
    histogram = metrics.histograms["latency"][()]
    assert len(histogram.buckets) == len(BUCKETS_MS)
    assert histogram.count == 100_000
    assert "latency_sum 4.2e+06" in metrics.render()


@pytest.mark.skipif(os.name != "posix", reason="sandbox process isolation requires POSIX")
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_s27_output_flood_is_terminated_and_memory_capped(stream: str) -> None:
    script = f"import sys\nwhile True: sys.{stream}.buffer.write(b'x'*4096); sys.{stream}.flush()"
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    start = time.monotonic()
    out, err, timed_out = communicate_capped(proc, 10)
    assert not timed_out and proc.returncode != 0
    assert "output limit exceeded" in err
    assert len(out) + len(err) <= MAX_CAPTURE_BYTES + 100
    assert time.monotonic() - start < 5


@pytest.mark.skipif(os.name != "posix", reason="sandbox process isolation requires POSIX")
def test_s27_timeout_kills_child_and_calls_container_cleanup() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    cleaned = []
    _, _, timed_out = communicate_capped(proc, 0.1, lambda: cleaned.append(True))
    assert timed_out and cleaned == [True] and proc.returncode != 0


def test_s31_service_boundary_closes_owned_provider() -> None:
    closed = []
    close_provider(SimpleNamespace(ai=SimpleNamespace(close=lambda: closed.append(True))))
    close_provider(SimpleNamespace(ai=None))
    assert closed == [True]


def test_s30_static_timeout_reaches_container_command(tmp_path: Path) -> None:
    from sentinel.core.configuration.config import RepoConfig
    from sentinel.core.domain.ports import SandboxResult
    from sentinel.sandbox.analysis import SandboxStaticRunner

    calls = []

    class Sandbox:
        isolation = "docker"

        def is_available(self) -> bool:
            return True

        def run(self, workspace, command, timeout_s):
            calls.append((command, timeout_s))
            return SandboxResult(
                command=command,
                exit_code=0,
                stdout='{"findings":[],"runs":[]}',
                stderr="",
                duration_ms=0,
                isolation="docker",
            )

    config = RepoConfig.model_validate({"static": {"timeout_s": 17}})
    SandboxStaticRunner(Sandbox(), config).run(tmp_path, ["a.py"])
    assert calls[0][0][-1] == "17" and calls[0][1] == 47


@pytest.mark.parametrize("option", ["--fail-on", "--format"])
def test_s33_invalid_output_policy_is_rejected_before_review(option: str) -> None:
    result = CliRunner().invoke(app, ["review", option, "typo"])
    assert result.exit_code == 2 and "must be" in result.output


def test_s33_pr_json_contains_only_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sentinel.apps.cli import review_commands as commands

    settings = Settings(provider="none", database_url=f"sqlite:///{tmp_path}/cli.db")
    monkeypatch.setattr(commands, "load_cli_settings", lambda **kw: settings)
    monkeypatch.setattr(commands, "github_factory", lambda _: lambda _: FakeGitHub().client())
    monkeypatch.setattr(
        commands.ReviewService, "run", lambda *args: ReviewResult(changeset=ChangeSet())
    )

    def forbid_progress(*args: object) -> None:
        pytest.fail("machine-readable output opened an interactive progress display")

    monkeypatch.setattr(commands, "LiveProgress", forbid_progress)
    result = CliRunner().invoke(
        app, ["review", "--pr", "7", "--repo", "acme/shop", "--format", "json", "--no-ai"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "completed"
