"""Fix engine: AI proposes a patch, deterministic checks and a sandbox validate it.

    finding -> AI patch (search/replace) -> apply to a scratch copy
            -> syntax check (parse only, nothing executed)
            -> re-run deterministic analysis: is the original issue gone? any new issues?
            -> run the test suite in the sandbox, before and after the patch
            -> validated / unverified / failed   (retry once with the failure feedback)

Built by ``bootstrap.build_fix_engine``; used by ``services/fixes.py`` and ``sentinel fix``.
The individual checks live in ``validation.py``.

The developer's repository is never modified here. ``apply_fix`` writes a validated
patch only on explicit request, and only if the files haven't changed since.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import AIFixResult, FixRequest
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import AnalysisRun, Finding
from sentinel.core.domain.ports import AIError, AIProvider
from sentinel.core.fixes.outcome import FixCheck, FixOutcome, FixStatus
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256, unified_diff
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.core.fixes.validation import (
    Sandbox,
    SyntaxChecker,
    check_no_new_issues,
    check_resolved,
    check_tests,
    detect_test_command,
    python_syntax,
)

__all__ = ["ApplyError", "FixEngine", "FixOutcome", "Sandbox", "SyntaxChecker", "apply_fix"]

DEFAULT_MAX_ATTEMPTS = 2
APPLICABLE_STATUSES = ("validated", "unverified")
CONFIRMING_CHECKS = ("finding-resolved", "tests")  # a pass here makes a fix "validated"


class StaticRunner(Protocol):
    """Runs the static analyzers on a directory (``analysis.static.runner``)."""

    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]:
        """Analyze ``files`` in ``workspace``."""


class ApplyError(SentinelError):
    """A fix cannot be applied (not validated, or the files changed since)."""


class FixEngine:
    """Generates a fix for one finding and validates it without touching the repository."""

    def __init__(
        self,
        ai: AIProvider,
        *,
        static_runner: StaticRunner,
        sandbox: Sandbox | None,
        config: RepoConfig | None = None,
        syntax_checkers: list[SyntaxChecker] | None = None,
        scratch: Callable[[Path], Path] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.ai = ai
        self.static_runner = static_runner
        self.sandbox = sandbox
        self.config = config or RepoConfig()
        self.syntax_checkers = syntax_checkers or [python_syntax]
        self.scratch = scratch or scratch_copy
        self.max_attempts = max_attempts

    def generate(self, finding: Finding, repo_root: Path) -> FixOutcome:
        """Ask the AI for a patch and validate it; on failure, retry with the failures."""
        try:
            original = (repo_root / finding.file).read_text(encoding="utf-8")
        except OSError as exc:
            return FixOutcome(status="error", error=f"cannot read {finding.file}: {exc}")
        files = {finding.file: original}
        feedback: str | None = None
        outcome = FixOutcome(status="error", error="no attempt made")
        for attempt in range(1, self.max_attempts + 1):
            try:
                answer = self.ai.generate_fix(_fix_request(finding, files, feedback))
            except AIError as exc:
                return FixOutcome(status="error", error=str(exc), attempts=attempt)
            outcome = self._try_patch(finding, repo_root, files, answer)
            outcome.provider, outcome.model, outcome.attempts = (
                answer.provider,
                answer.model,
                attempt,
            )
            if outcome.status != "failed":
                return outcome
            feedback = "\n".join(
                f"- {c.name}: {c.detail}" for c in outcome.checks if c.status == "failed"
            )
        return outcome

    def _try_patch(
        self, finding: Finding, repo_root: Path, files: dict[str, str], answer: AIFixResult
    ) -> FixOutcome:
        """Apply the proposed edits in memory and validate the result."""
        edits = answer.payload.edits
        try:
            after = apply_edits(files, edits)
        except PatchError as exc:
            apply_failed = FixCheck(name="apply", status="failed", detail=str(exc))
            return FixOutcome(
                status="failed", summary=answer.payload.summary, edits=edits, checks=[apply_failed]
            )
        outcome = self.validate(finding, repo_root, files, after)
        outcome.summary = answer.payload.summary
        outcome.edits = edits
        outcome.patch = unified_diff(files, after)
        outcome.original_hashes = {path: sha256(content) for path, content in files.items()}
        return outcome

    def validate(
        self, finding: Finding, repo_root: Path, before: dict[str, str], after: dict[str, str]
    ) -> FixOutcome:
        """Run every check on the patched files (``before``/``after``: path -> content)."""
        checks = [FixCheck(name="apply", status="passed", detail=f"{len(after)} file(s) patched")]
        errors = [
            e for p, c in after.items() for check in self.syntax_checkers if (e := check(p, c))
        ]
        if errors:
            checks.append(FixCheck(name="syntax", status="failed", detail="; ".join(errors)))
            return FixOutcome(status="failed", checks=checks)
        checks.append(FixCheck(name="syntax", status="passed", detail="patched files parse"))
        checks += self._checks_on_copies(finding, repo_root, after)
        isolation = self.sandbox.isolation if self.sandbox is not None else "none"
        return FixOutcome(status=_verdict(checks), checks=checks, isolation=isolation)

    def _checks_on_copies(
        self, finding: Finding, repo_root: Path, after: dict[str, str]
    ) -> list[FixCheck]:
        """Re-analysis and tests on two scratch copies: the original and the patched one."""
        base_dir = self.scratch(repo_root)
        patched_dir = self.scratch(repo_root)
        try:
            for rel, content in after.items():
                (patched_dir / rel).write_text(content, encoding="utf-8")
            targets = sorted(after)
            started = time.monotonic()
            findings_before, _ = self.static_runner.run(base_dir, targets)
            findings_after, runs = self.static_runner.run(patched_dir, targets)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            command = detect_test_command(repo_root, self.config)
            timeout = self.config.fix.timeout_s
            return [
                check_resolved(finding, findings_before, findings_after, elapsed_ms),
                check_no_new_issues(findings_before, findings_after, runs, elapsed_ms),
                check_tests(self.sandbox, command, timeout, base_dir, patched_dir),
            ]
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)
            shutil.rmtree(patched_dir, ignore_errors=True)


def apply_fix(repo_root: Path, outcome: FixOutcome) -> list[str]:
    """Write a validated patch into the real repository (explicit user action only)."""
    if outcome.status not in APPLICABLE_STATUSES:
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


def _fix_request(finding: Finding, files: dict[str, str], feedback: str | None) -> FixRequest:
    return FixRequest(
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


def _verdict(checks: list[FixCheck]) -> FixStatus:
    """Failed if any check failed; validated if a confirming check passed; else unverified."""
    if any(c.status == "failed" for c in checks):
        return "failed"
    if any(c.status == "passed" for c in checks if c.name in CONFIRMING_CHECKS):
        return "validated"
    return "unverified"
