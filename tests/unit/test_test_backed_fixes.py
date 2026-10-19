"""Logic fixes can use genuine before/after regression evidence without bypassing gates."""

from pathlib import Path
from typing import Literal

import pytest

from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from sentinel.core.fixes.outcome import FixCheck
from sentinel.core.fixes.regression import confirm_with_regression
from tests.fakes import ScriptedProvider
from tests.unit.test_fix_engine import FakeSandbox, engine, ok


@pytest.mark.parametrize(
    ("resolution_status", "regression_status", "target_changed", "promoted"),
    [
        ("skipped", "passed", True, True),
        ("skipped", "passed", False, False),
        ("skipped", "failed", True, False),
        ("skipped", "skipped", True, False),
        ("failed", "passed", True, False),
        ("error", "passed", True, False),
        ("passed", "passed", True, False),
    ],
)
def test_regression_only_fills_missing_resolution(
    resolution_status: Literal["passed", "failed", "skipped", "error"],
    regression_status: Literal["passed", "failed", "skipped", "error"],
    target_changed: bool,
    promoted: bool,
) -> None:
    resolution = FixCheck(name="finding-resolved", status=resolution_status)
    regression = FixCheck(name="regression-tests", status=regression_status)
    result = confirm_with_regression(resolution, regression, target_changed=target_changed)
    if promoted:
        assert result is not resolution
        assert result.status == "passed" and result.detail.startswith("test-backed:")
    else:
        assert result.status == resolution.status
        if resolution_status == "skipped" and regression_status == "passed":
            assert "cited source file did not change" in result.detail
            assert "Re-run review" in result.detail
            assert resolution.detail == ""  # Do not mutate the static evidence.
        else:
            assert result is resolution


def test_ai_only_logic_fix_requires_real_regression_gate(tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text("def retries(value):\n    return value or 3\n")
    finding = Finding(
        category=Category.BUG,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="Zero retries loses its meaning",
        explanation="Zero must disable retries.",
        file="settings.py",
        line_start=2,
        line_end=2,
        source=FindingSource.AI,
        origins=["ai:captured"],
    )
    proposal = {
        "summary": "Preserve zero and add a regression",
        "edits": [
            {
                "file": "settings.py",
                "search": "return value or 3",
                "replace": "return 3 if value is None else value",
            },
            {
                "file": "test_settings_regression.py",
                "operation": "create",
                "search": "",
                "replace": "from settings import retries\ndef test_zero():\n    assert retries(0) == 0\n",
            },
        ],
    }
    sandbox = FakeSandbox(ok(5), ok(), ok(1, "1 failed"), ok())
    outcome = engine(ScriptedProvider(fixes=[proposal]), sandbox, tmp_path).generate(
        finding, tmp_path
    )
    assert outcome.status == "validated", outcome.checks
    checks = {check.name: check for check in outcome.checks}
    assert checks["finding-resolved"].detail.startswith("test-backed:")
    assert checks["regression-tests"].status == "passed"
    assert len(sandbox.commands) == 4
    assert (tmp_path / "settings.py").read_text().endswith("return value or 3\n")
