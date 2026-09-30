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
from sentinel.core.domain.models import AnalysisRun, Finding, Language, StageName, StageRecord


class AIError(Exception):
    """Base class for provider failures the orchestrator knows how to degrade from."""


class AIConfigurationError(AIError):
    """Missing API key, unknown model, unreachable local server ..."""


class AIResponseError(AIError):
    """The provider answered, but not with something we can use."""


@runtime_checkable
class AIProvider(Protocol):
    name: str
    model: str

    def review(self, request: ReviewRequest) -> AIReviewResult: ...

    def generate_fix(self, request: FixRequest) -> AIFixResult: ...


@runtime_checkable
class LanguageAnalyzer(Protocol):
    language: Language
    extensions: tuple[str, ...]

    def analyze(self, path: str, source: str) -> FileSymbols: ...


@dataclass
class StaticAnalysisOutput:
    run: AnalysisRun
    findings: list[Finding] = field(default_factory=list)


@runtime_checkable
class StaticAnalyzer(Protocol):
    name: str
    languages: frozenset[Language]

    def is_available(self) -> bool: ...

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput: ...


class Cache(Protocol):
    """Content-addressed cache. Keys must be derived from content hashes, so an entry
    can never be stale: changed code produces a different key."""

    def get(self, namespace: str, key: str) -> str | None: ...

    def set(self, namespace: str, key: str, value: str) -> None: ...


class ProgressReporter(Protocol):
    def stage_changed(self, stage: StageRecord) -> None: ...


class NullProgress:
    def stage_changed(self, stage: StageRecord) -> None:
        return None


@dataclass
class SandboxResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    isolation: str = "unknown"

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxRunner(Protocol):
    isolation: str

    def is_available(self) -> bool: ...

    def run(self, workspace: Path, command: list[str], timeout_s: int = 120) -> SandboxResult: ...


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
