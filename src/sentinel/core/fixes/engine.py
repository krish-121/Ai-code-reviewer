"""Fix engine: AI proposes a patch, deterministic checks and a sandbox validate it.

    finding -> AI patch (search/replace) -> apply to a scratch copy
            -> syntax check (parse only, nothing executed)
            -> re-run deterministic analysis: is the original issue gone? any new issues?
            -> run the test suite in the sandbox, before and after the patch
            -> validated / unverified / failed   (retry once with the failure feedback)

The developer's repository is never modified here. ``apply_fix`` writes a validated
patch only on explicit request, and only if the files haven't changed since.
"""

from __future__ import annotations

import ast
import json
import shutil
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import FileEdit, FixRequest
from sentinel.core.domain.models import AnalysisRun, Finding, Severity
from sentinel.core.domain.ports import AIError, AIProvider, SandboxResult
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256, unified_diff
from sentinel.core.fixes.scratch import scratch_copy

CheckStatus = Literal["passed", "failed", "skipped", "error"]
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


class FixCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str = ""
    duration_ms: int = 0


class FixOutcome(BaseModel):
    status: Literal["validated", "unverified", "failed", "error"]
    summary: str = ""
    patch: str = ""
    edits: list[FileEdit] = Field(default_factory=list)
    original_hashes: dict[str, str] = Field(default_factory=dict)
    checks: list[FixCheck] = Field(default_factory=list)
    attempts: int = 0
    isolation: str = "none"
    error: str | None = None
    provider: str | None = None
    model: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "validated"


class StaticRunner(Protocol):
    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]: ...


class Sandbox(Protocol):
    isolation: str

    def is_available(self) -> bool: ...

    def run(self, workspace: Path, command: list[str], timeout_s: int = 120) -> SandboxResult: ...


SyntaxChecker = Callable[[str, str], str | None]


def python_syntax(path: str, content: str) -> str | None:
    if not path.endswith((".py", ".pyi")):
        return None
    try:
        ast.parse(content, filename=path)
    except SyntaxError as exc:
        return f"{path}:{exc.lineno}: {exc.msg}"
    return None


def detect_test_command(root: Path, config: RepoConfig) -> list[str] | None:
    if config.fix.test_command:
        return list(config.fix.test_command)
    has_py_tests = (
        any(root.glob("test_*.py"))
        or any(root.glob("tests/**/test_*.py"))
        or any(root.glob("**/tests/test_*.py"))
    )
    if has_py_tests:
        return ["python", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"]
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            script = json.loads(pkg.read_text()).get("scripts", {}).get("test", "")
        except (json.JSONDecodeError, OSError):
            script = ""
        if script and "no test specified" not in script:
            return ["npm", "test", "--silent"]
    return None


class FixEngine:
    def __init__(
        self,
        ai: AIProvider,
        *,
        static_runner: StaticRunner,
        sandbox: Sandbox | None,
        config: RepoConfig | None = None,
        syntax_checkers: list[SyntaxChecker] | None = None,
        scratch: Callable[[Path], Path] | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.ai = ai
        self.static_runner = static_runner
        self.sandbox = sandbox
        self.config = config or RepoConfig()
        self.syntax_checkers = syntax_checkers or [python_syntax]
        self.scratch = scratch or scratch_copy
        self.max_attempts = max_attempts

    # ------------------------------------------------------------------ generate
    def generate(self, finding: Finding, repo_root: Path) -> FixOutcome:
        path = repo_root / finding.file
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            return FixOutcome(status="error", error=f"cannot read {finding.file}: {exc}")
        files = {finding.file: original}
        feedback: str | None = None
        last = FixOutcome(status="error", error="no attempt made")
        for attempt in range(1, self.max_attempts + 1):
            request = FixRequest(
                finding_title=finding.title,
                finding_explanation=finding.explanation,
                category=finding.category,
                file=finding.file,
                line_start=finding.line_start,
                line_end=finding.line_end,
                suggested_fix=finding.suggested_fix,
                files=files,
                feedback=feedback,
            )
            try:
                ai_result = self.ai.generate_fix(request)
            except AIError as exc:
                return FixOutcome(status="error", error=str(exc), attempts=attempt)
            edits = ai_result.payload.edits
            base = {"provider": ai_result.provider, "model": ai_result.model, "attempts": attempt}
            try:
                after = apply_edits(files, edits)
            except PatchError as exc:
                feedback = str(exc)
                last = FixOutcome(
                    status="failed",
                    summary=ai_result.payload.summary,
                    edits=edits,
                    checks=[FixCheck(name="apply", status="failed", detail=str(exc))],
                    **base,
                )
                continue
            outcome = self.validate(finding, repo_root, files, after)
            outcome.summary = ai_result.payload.summary
            outcome.edits = edits
            outcome.patch = unified_diff(files, after)
            outcome.original_hashes = {p: sha256(c) for p, c in files.items()}
            outcome.provider, outcome.model, outcome.attempts = (
                ai_result.provider,
                ai_result.model,
                attempt,
            )
            if outcome.status != "failed":
                return outcome
            feedback = "\n".join(
                f"- {c.name}: {c.detail}" for c in outcome.checks if c.status == "failed"
            )
            last = outcome
        return last

    # ------------------------------------------------------------------ validate
    def validate(
        self, finding: Finding, repo_root: Path, before: dict[str, str], after: dict[str, str]
    ) -> FixOutcome:
        checks: list[FixCheck] = [
            FixCheck(name="apply", status="passed", detail=f"{len(after)} file(s) patched")
        ]
        errors = [e for p, c in after.items() for chk in self.syntax_checkers if (e := chk(p, c))]
        if errors:
            checks.append(FixCheck(name="syntax", status="failed", detail="; ".join(errors)))
            return FixOutcome(status="failed", checks=checks)
        checks.append(FixCheck(name="syntax", status="passed", detail="patched files parse"))

        base_dir = self.scratch(repo_root)
        patched_dir = self.scratch(repo_root)
        try:
            for rel, content in after.items():
                (patched_dir / rel).write_text(content, encoding="utf-8")
            targets = sorted(after)
            t0 = time.monotonic()
            before_f, _ = self.static_runner.run(base_dir, targets)
            after_f, runs = self.static_runner.run(patched_dir, targets)
            ms = int((time.monotonic() - t0) * 1000)
            checks.append(self._resolved(finding, before_f, after_f, ms))
            checks.append(self._no_new_issues(before_f, after_f, runs, ms))
            checks.append(self._tests(repo_root, base_dir, patched_dir))
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)
            shutil.rmtree(patched_dir, ignore_errors=True)
        isolation = self.sandbox.isolation if self.sandbox is not None else "none"
        if any(c.status == "failed" for c in checks):
            status: Literal["validated", "unverified", "failed"] = "failed"
        elif any(c.status == "passed" for c in checks if c.name in ("finding-resolved", "tests")):
            status = "validated"
        else:
            status = "unverified"
        return FixOutcome(status=status, checks=checks, isolation=isolation)

    @staticmethod
    def _rules(finding: Finding) -> set[str]:
        rules = {o.replace(":", "/", 1) for o in finding.origins if not o.startswith("ai:")}
        for tag in finding.tags:
            rules |= RULES_FOR_TAG.get(tag, set())
        return rules

    def _resolved(
        self, finding: Finding, before: list[Finding], after: list[Finding], ms: int
    ) -> FixCheck:
        rules = self._rules(finding)
        count_before = sum(1 for f in before if f.file == finding.file and f.rule_id in rules)
        if not rules or count_before == 0:
            return FixCheck(
                name="finding-resolved",
                status="skipped",
                duration_ms=ms,
                detail="no deterministic rule reproduces this finding; relying on tests",
            )
        count_after = sum(1 for f in after if f.file == finding.file and f.rule_id in rules)
        if count_after < count_before:
            return FixCheck(
                name="finding-resolved",
                status="passed",
                duration_ms=ms,
                detail=f"{', '.join(sorted(rules & {f.rule_id or '' for f in before}))} no "
                f"longer reported ({count_before} → {count_after})",
            )
        return FixCheck(
            name="finding-resolved",
            status="failed",
            duration_ms=ms,
            detail=f"the original issue is still reported after the patch ({count_after} left)",
        )

    @staticmethod
    def _no_new_issues(
        before: list[Finding], after: list[Finding], runs: list[AnalysisRun], ms: int
    ) -> FixCheck:
        def key(f: Finding) -> tuple[str, str, str]:
            return (f.file, f.rule_id or "", f.title)

        serious = {Severity.HIGH, Severity.MEDIUM}
        new = Counter(key(f) for f in after if f.severity in serious) - Counter(
            key(f) for f in before if f.severity in serious
        )
        tools = ", ".join(sorted(r.tool for r in runs if r.status == "ok")) or "none"
        if new:
            listed = "; ".join(f"{k[1]} {k[2]} ({k[0]})" for k in list(new)[:5])
            return FixCheck(
                name="no-new-issues",
                status="failed",
                duration_ms=ms,
                detail=f"patch introduces: {listed}",
            )
        return FixCheck(
            name="no-new-issues",
            status="passed",
            duration_ms=ms,
            detail=f"no new issues from {tools}",
        )

    def _tests(self, repo_root: Path, base_dir: Path, patched_dir: Path) -> FixCheck:
        command = detect_test_command(repo_root, self.config)
        if command is None:
            return FixCheck(name="tests", status="skipped", detail="no test command detected")
        if self.sandbox is None or not self.sandbox.is_available():
            return FixCheck(
                name="tests",
                status="skipped",
                detail="no sandbox available (start Docker, or opt in to the process sandbox); "
                "generated code was not executed",
            )
        timeout = self.config.fix.timeout_s
        baseline = self.sandbox.run(base_dir, command, timeout)
        if not baseline.ok:
            return FixCheck(
                name="tests",
                status="skipped",
                duration_ms=baseline.duration_ms,
                detail=f"tests already fail before the patch (exit {baseline.exit_code}); "
                "cannot attribute failures",
            )
        result = self.sandbox.run(patched_dir, command, timeout)
        if result.ok:
            return FixCheck(
                name="tests",
                status="passed",
                duration_ms=result.duration_ms,
                detail=f"`{' '.join(command)}` passes in {self.sandbox.isolation} sandbox",
            )
        tail = (result.stdout + result.stderr).strip().splitlines()[-8:]
        reason = "timed out" if result.timed_out else f"exit {result.exit_code}"
        return FixCheck(
            name="tests",
            status="failed",
            duration_ms=result.duration_ms,
            detail=f"tests fail after the patch ({reason}): " + " | ".join(tail),
        )


class ApplyError(Exception):
    pass


def apply_fix(repo_root: Path, outcome: FixOutcome) -> list[str]:
    """Write a validated patch into the real repository (explicit user action only)."""
    if outcome.status not in ("validated", "unverified"):
        raise ApplyError(f"refusing to apply a fix with status {outcome.status}")
    files = {}
    for path, digest in outcome.original_hashes.items():
        current = (repo_root / path).read_text(encoding="utf-8")
        if sha256(current) != digest:
            raise ApplyError(f"{path} changed since the fix was generated; regenerate the fix")
        files[path] = current
    after = apply_edits(files, outcome.edits)
    for path, content in after.items():
        (repo_root / path).write_text(content, encoding="utf-8")
    return sorted(after)
