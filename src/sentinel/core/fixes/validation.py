"""The checks a proposed fix must pass, run by ``FixEngine.validate`` (``engine.py``).

1. *syntax*: the patched files still parse (nothing is executed);
2. *finding-resolved*: the deterministic rule that reproduces the finding no longer fires;
3. *no-new-issues*: no new medium/high findings appear in the patched files;
4. *tests*: the test suite passes in the sandbox after the patch (and passed before it).
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import AnalysisRun, Finding, Severity, ToolStatus
from sentinel.core.domain.ports import SandboxResult
from sentinel.core.fixes.outcome import FixCheck

# Deterministic rules that reproduce a finding with this tag (so a fix can be re-checked).
RULES_FOR_TAG = {
    "sql-injection": {"sentinel/sql-injection", "ruff/S608", "bandit/B608"},
    "command-injection": {"sentinel/command-injection", "ruff/S602", "ruff/S605"},
    "code-injection": {"sentinel/code-injection", "ruff/S307", "eslint/no-eval"},
    "n+1": {"sentinel/n-plus-one"},
    "blocking-in-async": {"sentinel/blocking-in-async"},
    "missing-await": {"sentinel/missing-await"},
    "quadratic": {"sentinel/quadratic-loop"},
    "swallowed-exception": {"sentinel/swallowed-exception", "ruff/S110"},
    "deserialization": {"sentinel/unsafe-deserialization", "sentinel/unsafe-yaml"},
    "weak-crypto": {"sentinel/weak-hash", "ruff/S324"},
}
SERIOUS = frozenset({Severity.HIGH, Severity.MEDIUM})
PYTEST_COMMAND = ["python", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"]
NPM_TEST_COMMAND = ["npm", "test", "--silent"]
NPM_PLACEHOLDER_TEST = "no test specified"
MAX_LISTED_ISSUES = 5
FAILURE_TAIL_LINES = 8

# (path, content) -> error message, or None when the file is fine / not this checker's language
SyntaxChecker = Callable[[str, str], str | None]


class Sandbox(Protocol):
    """Where the tests of a patched copy run (see ``sentinel/sandbox``)."""

    isolation: str

    def is_available(self) -> bool:
        """True when the sandbox can be used on this machine."""

    def run(self, workspace: Path, command: list[str], timeout_s: int = 120) -> SandboxResult:
        """Run ``command`` inside ``workspace``."""


def python_syntax(path: str, content: str) -> str | None:
    """Syntax error in a Python file, if any."""
    if not path.endswith((".py", ".pyi")):
        return None
    try:
        ast.parse(content, filename=path)
    except SyntaxError as exc:
        return f"{path}:{exc.lineno}: {exc.msg}"
    return None


def detect_test_command(root: Path, config: RepoConfig) -> list[str] | None:
    """The configured test command, else pytest or ``npm test`` when the repo has tests."""
    if config.fix.test_command:
        return list(config.fix.test_command)
    has_python_tests = (
        any(root.glob("test_*.py"))
        or any(root.glob("tests/**/test_*.py"))
        or any(root.glob("**/tests/test_*.py"))
    )
    if has_python_tests:
        return PYTEST_COMMAND
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            script = json.loads(package_json.read_text()).get("scripts", {}).get("test", "")
        except (json.JSONDecodeError, OSError):
            script = ""
        if script and NPM_PLACEHOLDER_TEST not in script:
            return NPM_TEST_COMMAND
    return None


def reproducing_rules(finding: Finding) -> set[str]:
    """Rule ids that detect this finding: its own tool origins plus rules for its tags."""
    rules = {o.replace(":", "/", 1) for o in finding.origins if not o.startswith("ai:")}
    for tag in finding.tags:
        rules |= RULES_FOR_TAG.get(tag, set())
    return rules


def check_resolved(
    finding: Finding, before: list[Finding], after: list[Finding], duration_ms: int
) -> FixCheck:
    """Passed when a rule that reported the finding before the patch reports less after it."""
    rules = reproducing_rules(finding)
    count_before = sum(1 for f in before if f.file == finding.file and f.rule_id in rules)
    if not rules or count_before == 0:
        detail = "no deterministic rule reproduces this finding; relying on tests"
        return FixCheck(
            name="finding-resolved", status="skipped", duration_ms=duration_ms, detail=detail
        )
    count_after = sum(1 for f in after if f.file == finding.file and f.rule_id in rules)
    if count_after < count_before:
        fired = ", ".join(sorted(rules & {f.rule_id or "" for f in before}))
        detail = f"{fired} no longer reported ({count_before} → {count_after})"
        return FixCheck(
            name="finding-resolved", status="passed", duration_ms=duration_ms, detail=detail
        )
    detail = f"the original issue is still reported after the patch ({count_after} left)"
    return FixCheck(
        name="finding-resolved", status="failed", duration_ms=duration_ms, detail=detail
    )


def check_no_new_issues(
    before: list[Finding], after: list[Finding], runs: list[AnalysisRun], duration_ms: int
) -> FixCheck:
    """Failed when the patched files have medium/high findings the originals did not."""

    def key(f: Finding) -> tuple[str, str, str]:
        return (f.file, f.rule_id or "", f.title)

    new = Counter(key(f) for f in after if f.severity in SERIOUS) - Counter(
        key(f) for f in before if f.severity in SERIOUS
    )
    if new:
        listed = "; ".join(
            f"{rule} {title} ({file})" for file, rule, title in list(new)[:MAX_LISTED_ISSUES]
        )
        return FixCheck(
            name="no-new-issues",
            status="failed",
            duration_ms=duration_ms,
            detail=f"patch introduces: {listed}",
        )
    tools = ", ".join(sorted(r.tool for r in runs if r.status == ToolStatus.OK)) or "none"
    return FixCheck(
        name="no-new-issues",
        status="passed",
        duration_ms=duration_ms,
        detail=f"no new issues from {tools}",
    )


def check_tests(
    sandbox: Sandbox | None,
    command: list[str] | None,
    timeout_s: int,
    base_dir: Path,
    patched_dir: Path,
) -> FixCheck:
    """Run the tests on the original and on the patched copy, both inside the sandbox."""
    if command is None:
        return FixCheck(name="tests", status="skipped", detail="no test command detected")
    if sandbox is None or not sandbox.is_available():
        return FixCheck(
            name="tests",
            status="skipped",
            detail="no sandbox available (start Docker, or opt in to the process sandbox); "
            "generated code was not executed",
        )
    baseline = sandbox.run(base_dir, command, timeout_s)
    if not baseline.ok:
        return FixCheck(
            name="tests",
            status="skipped",
            duration_ms=baseline.duration_ms,
            detail=f"tests already fail before the patch (exit {baseline.exit_code}); "
            "cannot attribute failures",
        )
    patched = sandbox.run(patched_dir, command, timeout_s)
    if patched.ok:
        return FixCheck(
            name="tests",
            status="passed",
            duration_ms=patched.duration_ms,
            detail=f"`{' '.join(command)}` passes in {sandbox.isolation} sandbox",
        )
    tail = (patched.stdout + patched.stderr).strip().splitlines()[-FAILURE_TAIL_LINES:]
    reason = "timed out" if patched.timed_out else f"exit {patched.exit_code}"
    return FixCheck(
        name="tests",
        status="failed",
        duration_ms=patched.duration_ms,
        detail=f"tests fail after the patch ({reason}): " + " | ".join(tail),
    )
