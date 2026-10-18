"""Dedicated fix workers must not consume review jobs or silently lose isolation."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sentinel.apps.cli.main import app
from sentinel.apps.worker.health import ready
from sentinel.apps.worker.main import Worker
from sentinel.core.configuration.config import Settings, load_settings
from sentinel.core.domain.models import ChangeSet, ReviewResult
from sentinel.core.fixes.outcome import FixOutcome
from sentinel.infrastructure.database.models import Job
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.queue import jobs
from tests.helpers import DATABASE_BACKENDS, fresh_database_url


@pytest.mark.parametrize("backend", DATABASE_BACKENDS)
def test_separate_workers_claim_only_their_job_kinds(tmp_path: Path, backend: str) -> None:
    db = Database(fresh_database_url(backend, tmp_path))
    db.create_all()
    calls = []
    reviews = SimpleNamespace(
        run=lambda rid: calls.append(("review", rid)) or ReviewResult(changeset=ChangeSet()),
        publish=lambda rid: calls.append(("publish", rid)),
    )
    fixes = SimpleNamespace(
        run=lambda fid: calls.append(("fix", fid)) or FixOutcome(status="validated")
    )
    with db.transaction() as session:
        ids = [
            jobs.enqueue(session, kind, {"review_id": "r", "fix_id": "f"}).id
            for kind in ("fix", "review", "publish")
        ]
    regular = Worker(db, reviews, fixes, worker_id="ordinary", kinds=["review", "publish"])
    validation = Worker(db, reviews, fixes, worker_id="isolated", kinds=["fix"])
    assert regular.run_once() and regular.run_once() and not regular.run_once()
    assert calls == [("review", "r"), ("publish", "r")]
    assert validation.run_once() and not validation.run_once()
    assert calls[-1] == ("fix", "f")
    with db.session() as session:
        completed = [session.get_one(Job, job_id) for job_id in ids]
        assert [job.status for job in completed] == [jobs.DONE] * 3
        assert [job.worker_id for job in completed] == ["isolated", "ordinary", "ordinary"]
    with pytest.raises(ValueError, match="worker kinds"):
        Worker(db, reviews, fixes, kinds=["typo"])
    with pytest.raises(ValueError, match="worker kinds"):
        Worker(db, reviews, fixes, kinds=[])


def test_fix_worker_cli_refuses_missing_docker_before_opening_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.apps.cli import server_commands as commands

    monkeypatch.setattr(commands, "load_cli_settings", lambda: Settings())
    monkeypatch.setattr(commands, "build_sandbox", lambda _: None)
    result = CliRunner().invoke(app, ["worker", "--kind", "fix", "--require-sandbox"])
    assert result.exit_code != 0 and "Docker fix sandbox is unavailable" in result.output
    result = CliRunner().invoke(app, ["worker", "--kind", "typo"])
    assert result.exit_code == 2 and "worker kinds" in result.output


def test_worker_health_requires_current_schema_and_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sentinel.apps.worker import health

    settings = Settings(database_url=f"sqlite:///{tmp_path}/health.db")
    assert not ready(settings)
    db = Database(settings.database_url)
    db.create_all()
    assert ready(settings)
    monkeypatch.setattr(health, "build_sandbox", lambda _: None)
    assert not ready(settings, require_sandbox=True)
    monkeypatch.setattr(health, "build_sandbox", lambda _: SimpleNamespace(isolation="process"))
    assert not ready(settings, require_sandbox=True)
    monkeypatch.setattr(health, "build_sandbox", lambda _: SimpleNamespace(isolation="docker"))
    assert ready(settings, require_sandbox=True)


def test_copy_transport_loads_from_environment_and_rejects_typos() -> None:
    settings = load_settings(env={"SENTINEL_SANDBOX_TRANSPORT": "copy"})
    assert settings.sandbox_transport == "copy"
    with pytest.raises(ValueError, match="sandbox_transport"):
        load_settings(env={"SENTINEL_SANDBOX_TRANSPORT": "cop"})
