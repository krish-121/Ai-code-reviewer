"""Check generated tests against original and patched code inside Docker only."""

import re
import shutil
from collections.abc import Callable
from pathlib import Path

from sentinel.core.configuration.config import RepoConfig
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
        if old.timed_out or old.exit_code != 1 or not re.search(r"\b[1-9]\d* failed\b", old.stdout):
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
