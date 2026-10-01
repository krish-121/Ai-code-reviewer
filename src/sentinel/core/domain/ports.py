"""Ports: the interfaces the core depends on.

Concrete implementations live in outer layers (``sentinel.ai.providers``,
``sentinel.analysis.static``, ``sentinel.sandbox`` ...). The review orchestrator only
knows these protocols, so swapping Gemini for Claude, or Docker for another sandbox,
never touches core logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from sentinel.core.domain.ai import AIFixResult, AIReviewResult, FixRequest, ReviewRequest
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import AnalysisRun, Finding, Language, StageName, StageRecord


class AIError(SentinelError):
    """Base class for provider failures the orchestrator knows how to degrade from."""


class AIConfigurationError(AIError):
    """Missing API key, unknown model, unreachable local server ..."""


class AIResponseError(AIError):
    """The provider answered, but not with something we can use."""


@runtime_checkable
class AIProvider(Protocol):
    """Anything that can review a change and propose a fix (Claude, Gemini, Ollama, test fakes)."""

    name: str
    model: str

    def review(self, request: ReviewRequest) -> AIReviewResult:
        """Review a change and return validated findings."""

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        """Propose search/replace edits that fix one finding."""


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """Extracts symbols, imports and calls from one source file."""

    language: Language
    extensions: tuple[str, ...]

    def analyze(self, path: str, source: str) -> FileSymbols:
        """Parse ``source`` and return what it defines and uses."""


@dataclass
class StaticAnalysisOutput:
    """What one static analyzer produced: its run record and its findings."""

    run: AnalysisRun
    findings: list[Finding] = field(default_factory=list)


@runtime_checkable
class StaticAnalyzer(Protocol):
    """A deterministic tool such as Ruff, mypy, Bandit or ESLint."""

    name: str
    languages: frozenset[Language]

    def is_available(self) -> bool:
        """True when the tool can run on this machine."""

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        """Analyze ``files`` inside ``workspace`` and return normalized findings."""


class Cache(Protocol):
    """Content-addressed cache.

    Keys must be derived from content hashes, so an entry can never be stale: changed
    code produces a different key.
    """

    def get(self, namespace: str, key: str) -> str | None:
        """Cached value for ``key`` in ``namespace``, or None."""

    def set(self, namespace: str, key: str, value: str) -> None:
        """Store ``value`` under ``key`` in ``namespace``."""


class ProgressReporter(Protocol):
    """Receives stage updates while a review runs (DB writer, terminal spinner ...)."""

    def stage_changed(self, stage: StageRecord) -> None:
        """Called every time a stage starts, finishes, fails or is skipped."""


class NullProgress:
    """Progress reporter that ignores every update."""

    def stage_changed(self, stage: StageRecord) -> None:
        """Ignore the update."""
        return


@dataclass
class SandboxResult:
    """Outcome of running one command inside a sandbox."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    isolation: str = "unknown"

    @property
    def ok(self) -> bool:
        """True when the command exited 0 within its time limit."""
        return self.exit_code == 0 and not self.timed_out


class SandboxRunner(Protocol):
    """Runs commands in an isolated copy of a repository (Docker or a restricted process)."""

    isolation: str

    def is_available(self) -> bool:
        """True when this kind of sandbox can be used here."""

    def run(self, workspace: Path, command: list[str], timeout_s: int = 120) -> SandboxResult:
        """Run ``command`` in ``workspace`` and capture its output."""


__all__ = [
    "AIConfigurationError",
    "AIError",
    "AIProvider",
    "AIResponseError",
    "Cache",
    "LanguageAnalyzer",
    "NullProgress",
    "ProgressReporter",
    "SandboxResult",
    "SandboxRunner",
    "StageName",
    "StaticAnalysisOutput",
    "StaticAnalyzer",
]
