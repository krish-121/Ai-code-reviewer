"""Incomplete validation cannot reach working-tree writes through any delivery surface."""

from pathlib import Path

import pytest

from sentinel.apps.api.serializers import fix_json
from sentinel.core.domain.ai import FileEdit
from sentinel.core.fixes.apply import ApplyError, apply_fix
from sentinel.core.fixes.outcome import FixOutcome
from sentinel.core.fixes.patch import sha256
from sentinel.infrastructure.database.models import FixAttempt
from sentinel.sandbox.runners import MAX_REPORT_OUTPUT, DockerSandbox


@pytest.mark.parametrize("status", ["unverified", "failed", "error"])
def test_nonvalidated_patch_is_refused_before_any_write(tmp_path: Path, status: str) -> None:
    target = tmp_path / "app.py"
    target.write_text("value = 1\n")
    proposal = FixOutcome.model_validate(
        {
            "status": status,
            "edits": [FileEdit(file="app.py", search="1", replace="2")],
            "original_hashes": {"app.py": sha256(target.read_text())},
        }
    )
    with pytest.raises(ApplyError, match=f"status {status}"):
        apply_fix(tmp_path, proposal)
    assert target.read_text() == "value = 1\n"


@pytest.mark.parametrize(
    "status", ["queued", "running", "unverified", "failed", "error", "applied", "rejected"]
)
def test_api_never_advertises_apply_for_nonvalidated_attempts(status: str) -> None:
    attempt = FixAttempt(id="X-test", finding_id="F-test", status=status, checks=[], attempts=1)
    assert not fix_json(attempt, repository_is_local=True)["can_apply"]


@pytest.mark.parametrize("local", [True, False])
def test_api_advertises_validated_apply_only_for_local_repositories(local: bool) -> None:
    attempt = FixAttempt(
        id="X-test", finding_id="F-test", status="validated", checks=[], attempts=1
    )
    assert fix_json(attempt, repository_is_local=local)["can_apply"] is local


@pytest.mark.parametrize("limit", [0, -1, MAX_REPORT_OUTPUT + 1])
def test_sandbox_output_limits_are_bounded_before_process_start(tmp_path: Path, limit: int) -> None:
    with pytest.raises(ValueError, match="output limit"):
        DockerSandbox(docker="must-not-execute").run(tmp_path, ["unused"], output_limit=limit)
