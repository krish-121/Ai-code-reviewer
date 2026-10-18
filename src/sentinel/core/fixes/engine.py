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

from sentinel.analysis.diff.secrets import redact_text
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import AIFixResult, FixRequest
from sentinel.core.domain.models import AnalysisRun, Finding
from sentinel.core.domain.ports import AIError, AIProvider
from sentinel.core.fixes.apply import ApplyError, apply_fix
from sentinel.core.fixes.context import FixContext, analysis_targets, fix_context
from sentinel.core.fixes.outcome import FixCheck, FixOutcome, FixStatus
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256, unified_diff
from sentinel.core.fixes.regression import check_regression_tests, confirm_with_regression
from sentinel.core.fixes.safety import check_fix_finding, check_fix_path
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.core.fixes.validation import (
    Sandbox,
    SyntaxChecker,
    check_analysis,
    check_no_new_issues,
    check_resolved,
    check_tests,
    detect_test_command,
    python_syntax,
)
from sentinel.core.paths import (
    RepositoryPathError,
    create_repository_text,
    write_repository_text,
)

__all__ = ["ApplyError", "FixEngine", "FixOutcome", "Sandbox", "SyntaxChecker", "apply_fix"]

DEFAULT_MAX_ATTEMPTS = 2
CONFIRMING_CHECKS = ("analysis", "finding-resolved", "no-new-issues", "tests")


class StaticRunner(Protocol):
    """Runs the static analyzers on a directory (``analysis.static.runner``)."""

    isolation: str

    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]:
        """Analyze ``files`` in ``workspace``."""


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
            check_fix_finding(finding, self.config)
            context = fix_context(repo_root, finding, self.config)
        except (OSError, UnicodeError, RepositoryPathError) as exc:
            return FixOutcome(status="error", error=f"cannot read {finding.file}: {exc}")
        files = context.files
        feedback: str | None = None
        outcome = FixOutcome(status="error", error="no attempt made")
        for attempt in range(1, self.max_attempts + 1):
            try:
                answer = self.ai.generate_fix(
                    _fix_request(finding, files, feedback, context.new_files)
                )
            except AIError as exc:
                return FixOutcome(status="error", error=str(exc), attempts=attempt)
            outcome = self._try_patch(finding, repo_root, context, answer)
            outcome.provider, outcome.model, outcome.attempts = (
                answer.provider,
                answer.model,
                attempt,
            )
            outcome.fallback_events = answer.fallback_events
            if outcome.status != "failed":
                return outcome
            feedback = "\n".join(
                f"- {c.name}: {c.detail}" for c in outcome.checks if c.status == "failed"
            )
        return outcome

    def _try_patch(
        self, finding: Finding, repo_root: Path, context: FixContext, answer: AIFixResult
    ) -> FixOutcome:
        """Apply the proposed edits in memory and validate the result."""
        edits = answer.payload.edits
        files = context.files
        try:
            after = apply_edits(files, edits, context.new_files)
        except (PatchError, RepositoryPathError) as exc:
            apply_failed = FixCheck(name="apply", status="failed", detail=str(exc))
            return FixOutcome(
                status="failed", summary=answer.payload.summary, edits=edits, checks=[apply_failed]
            )
        outcome = self.validate(finding, repo_root, files, after)
        outcome.summary = answer.payload.summary
        outcome.edits = edits
        outcome.patch = unified_diff(files, after)
        outcome.original_hashes = {path: sha256(content) for path, content in files.items()}
        outcome.original_hashes.update({path: None for path in after if path not in files})
        return outcome

    def validate(
        self, finding: Finding, repo_root: Path, before: dict[str, str], after: dict[str, str]
    ) -> FixOutcome:
        """Run every check on the patched files (``before``/``after``: path -> content)."""
        try:
            check_fix_finding(finding, self.config)
            for path in before.keys() | after.keys():
                check_fix_path(path, self.config)
        except RepositoryPathError as exc:
            return FixOutcome(status="error", error=str(exc))
        checks = [FixCheck(name="apply", status="passed", detail=f"{len(after)} file(s) patched")]
        errors = [
            e for p, c in after.items() for check in self.syntax_checkers if (e := check(p, c))
        ]
        if errors:
            checks.append(FixCheck(name="syntax", status="failed", detail="; ".join(errors)))
            return FixOutcome(status="failed", checks=checks)
        checks.append(FixCheck(name="syntax", status="passed", detail="patched files parse"))
        checks += self._checks_on_copies(finding, repo_root, before, after)
        isolation = self.sandbox.isolation if self.sandbox is not None else "none"
        return FixOutcome(status=_verdict(checks), checks=checks, isolation=isolation)

    def _checks_on_copies(
        self, finding: Finding, repo_root: Path, before: dict[str, str], after: dict[str, str]
    ) -> list[FixCheck]:
        """Re-analysis and tests on two scratch copies: the original and the patched one."""
        if getattr(self.static_runner, "isolation", None) != "docker":
            return [FixCheck(name="analysis", status="skipped", detail="Docker analysis required")]
        base_dir = self.scratch(repo_root)
        patched_dir = self.scratch(repo_root)
        try:
            for rel, content in after.items():
                if rel in before:
                    write_repository_text(patched_dir, rel, content)
                else:
                    create_repository_text(patched_dir, rel, content)
            try:
                baseline_targets = analysis_targets(base_dir, self.config)
                targets = analysis_targets(patched_dir, self.config)
            except RepositoryPathError as exc:
                return [FixCheck(name="analysis", status="skipped", detail=str(exc))]
            started = time.monotonic()
            findings_before, baseline_runs = self.static_runner.run(base_dir, baseline_targets)
            findings_after, runs = self.static_runner.run(patched_dir, targets)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            command = detect_test_command(patched_dir, self.config)
            timeout = self.config.fix.timeout_s
            analysis = check_analysis(baseline_runs, runs)
            if analysis.status != "passed":
                return [analysis]
            resolution = check_resolved(finding, findings_before, findings_after, elapsed_ms)
            checks = [
                check_no_new_issues(findings_before, findings_after, runs, elapsed_ms),
                check_tests(
                    self.sandbox,
                    command,
                    timeout,
                    base_dir,
                    patched_dir,
                    allow_empty_baseline=bool(after.keys() - before.keys()),
                ),
            ]
            new_files = {p: after[p] for p in after.keys() - before.keys()}
            if new_files:
                regression = check_regression_tests(
                    self.sandbox, repo_root, patched_dir, new_files, self.config, self.scratch
                )
                checks.append(regression)
                resolution = confirm_with_regression(
                    resolution,
                    regression,
                    target_changed=before.get(finding.file) != after.get(finding.file),
                )
            return [analysis, resolution, *checks]
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)
            shutil.rmtree(patched_dir, ignore_errors=True)


def _fix_request(
    finding: Finding,
    files: dict[str, str],
    feedback: str | None,
    new_files: list[str] | None = None,
) -> FixRequest:
    return FixRequest(
        finding_title=redact_text(finding.title)[0],
        finding_explanation=redact_text(finding.explanation)[0],
        category=finding.category,
        file=finding.file,
        line_start=finding.line_start,
        line_end=finding.line_end,
        suggested_fix=redact_text(finding.suggested_fix)[0] if finding.suggested_fix else None,
        files={path: redact_text(content)[0] for path, content in files.items()},
        allowed_new_files=new_files or [],
        feedback=redact_text(feedback)[0] if feedback else None,
    )


def _verdict(checks: list[FixCheck]) -> FixStatus:
    """Only complete, successful validation can confirm a fix."""
    if any(c.status == "failed" for c in checks):
        return "failed"
    passed = {c.name for c in checks if c.status == "passed"}
    if set(CONFIRMING_CHECKS) <= passed and all(c.status == "passed" for c in checks):
        return "validated"
    return "unverified"
