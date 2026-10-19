"""A helper-only patch must not claim the cited source file itself changed."""

from pathlib import Path

import pytest

from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from tests.fakes import ScriptedProvider
from tests.unit.test_fix_engine import FakeSandbox, engine, ok


@pytest.mark.parametrize("include_unchanged_target", [False, True])
def test_helper_only_patch_cannot_claim_target_changed(
    tmp_path: Path, include_unchanged_target: bool
) -> None:
    (tmp_path / "service.py").write_text("from helper import retries\nvalue = retries(0)\n")
    (tmp_path / "helper.py").write_text("def retries(value):\n    return value or 3\n")
    finding = Finding(
        category=Category.BUG,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="Zero retries is lost in the service",
        explanation="A helper converts zero into three.",
        file="service.py",
        line_start=2,
        line_end=2,
        source=FindingSource.AI,
        origins=["ai:captured"],
    )
    edits = [
        {"file": "helper.py", "search": "value or 3", "replace": "3 if value is None else value"},
        {
            "file": "test_service_regression.py",
            "operation": "create",
            "search": "",
            "replace": "from service import value\ndef test_zero():\n    assert value == 0\n",
        },
    ]
    if include_unchanged_target:
        edits.append(
            {"file": "service.py", "search": "value = retries(0)", "replace": "value = retries(0)"}
        )
    provider = ScriptedProvider(fixes=[{"summary": "Change helper and add test", "edits": edits}])
    sandbox = FakeSandbox(ok(5), ok(), ok(1, "1 failed"), ok())

    outcome = engine(provider, sandbox, tmp_path).generate(finding, tmp_path)

    assert outcome.status == "unverified", outcome.checks
    resolution = next(check for check in outcome.checks if check.name == "finding-resolved")
    assert resolution.status == "skipped"
    assert "cited source file did not change" in resolution.detail
    assert "Re-run review" in resolution.detail
    assert (tmp_path / "helper.py").read_text().endswith("return value or 3\n")
