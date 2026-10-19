"""Check generated tests against original and patched code inside Docker only."""

import re
import shutil
from collections.abc import Callable
from pathlib import Path

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ports import SandboxResult
from sentinel.core.fixes.outcome import FixCheck
from sentinel.core.fixes.validation import PYTEST_COMMAND, Sandbox
from sentinel.core.paths import create_repository_text


def check_regression_tests(
    sandbox: Sandbox | None,
    root: Path,
    patched: Path,
    new_files: dict[str, str],
    config: RepoConfig,
    scratch: Callable[[Path], Path],
) -> FixCheck:
    """Require new tests to fail against the original code and pass against the patch."""
    command = _command(config, sorted(new_files))
    if sandbox is None or sandbox.isolation != "docker" or not sandbox.is_available():
        return FixCheck(name="regression-tests", status="skipped", detail="Docker is unavailable")
    if command is None:
        return FixCheck(
            name="regression-tests",
            status="skipped",
            detail="configure fix.regression_command with {files} for this test framework",
        )
    baseline = scratch(root)
    try:
        for path, content in new_files.items():
            create_repository_text(baseline, path, content)
        old = sandbox.run(baseline, command, config.fix.timeout_s)
        if not _test_failed(old):
            return FixCheck(
                name="regression-tests",
                status="failed",
                detail="new tests must fail against original code; "
                "collection errors and timeouts do not establish a regression",
            )
        result = sandbox.run(patched, command, config.fix.timeout_s)
        return FixCheck(
            name="regression-tests",
            status="passed" if result.ok else "failed",
            detail="new tests fail before and pass after"
            if result.ok
            else "new tests fail after the patch",
            duration_ms=old.duration_ms + result.duration_ms,
        )
    finally:
        shutil.rmtree(baseline, ignore_errors=True)


def _command(config: RepoConfig, files: list[str]) -> list[str] | None:
    if config.fix.regression_command:
        if "{files}" not in config.fix.regression_command:
            return None
        return [
            part
            for argument in config.fix.regression_command
            for part in (files if argument == "{files}" else [argument])
        ]
    if all(path.endswith(".py") for path in files):
        return [*PYTEST_COMMAND, *files]
    return None


def _test_failed(result: SandboxResult) -> bool:
    """Recognize pytest or Node TAP test failures, excluding failed collection and timeouts.

    An exit code alone cannot distinguish a reproduced bug from a missing import.
    Node's built-in test runner reports test failures as TAP diagnostics rather than
    pytest's ``N failed`` summary. Other reporters remain unsupported and fail closed.
    """
    if result.timed_out or result.exit_code != 1:
        return False
    output = result.stdout
    if not re.search(r"(?m)^TAP version 13$", output):
        summaries = re.findall(r"(?m)^(?:=+\s*)?([1-9]\d* failed\b[^\n]*)$", output)
        return bool(summaries) and not re.search(r"\b[1-9]\d* errors?\b", summaries[-1])
    return _node_test_failed(output)


def _node_test_failed(output: str) -> bool:
    """Require completed test-case failures, not just a failed file-loading process."""
    if not re.search(r"(?m)^# fail [1-9]\d*$", output):
        return False
    if not re.search(r"(?m)^# cancelled 0$", output):
        return False
    diagnostics = re.findall(r"(?ms)^\s*not ok \d+ - [^\n]+\n(.*?^\s*\.\.\.\s*$)", output)
    cases = [block for block in diagnostics if "'testCodeFailure'" in block]
    # A top-level missing import fails the file process. A TypeError *inside* a
    # named test is a real reproduced failure, just as it is for pytest.
    return bool(cases) and all(
        re.search(r"(?m)^\s+code: ['\"]ERR_ASSERTION['\"]$", block)
        or re.search(r"(?m)^\s+(?:async )?TestContext\.", block)
        for block in cases
    )


def confirm_with_regression(
    resolution: FixCheck, regression: FixCheck, *, target_changed: bool
) -> FixCheck:
    """Use a reproduced test failure when static rules cannot confirm a logic fix.

    This is test-backed validation, not a proof of all behaviour. It is considered
    only after complete Docker analysis, with the same generated test failing on
    original code and passing on the patch. A failed static recheck stays failed;
    editing only other context files cannot confirm the targeted finding.
    """
    if resolution.status != "skipped" or regression.status != "passed":
        return resolution
    if not target_changed:
        return resolution.model_copy(
            update={
                "detail": "new regression tests pass, but the cited source file did not change; "
                "test-backed attribution requires a changed target. Re-run review to locate "
                "a dependency's root cause before generating a new fix"
            }
        )
    return FixCheck(
        name="finding-resolved",
        status="passed",
        detail="test-backed: the same new regression test fails before and passes after; "
        "the targeted source file changed (no static rule confirms this finding)",
        duration_ms=regression.duration_ms,
    )
