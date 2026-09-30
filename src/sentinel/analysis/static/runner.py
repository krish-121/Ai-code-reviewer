"""Run every applicable static analyzer over the changed files, in parallel."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sentinel.analysis.ast.registry import LanguageRegistry
from sentinel.analysis.diff.parser import detect_language
from sentinel.analysis.static.builtin_security import BuiltinAnalyzer
from sentinel.analysis.static.js_tools import ESLintAnalyzer, TscAnalyzer
from sentinel.analysis.static.python_tools import BanditAnalyzer, MypyAnalyzer, RuffAnalyzer
from sentinel.core.domain.models import AnalysisRun, Finding
from sentinel.core.domain.ports import StaticAnalysisOutput, StaticAnalyzer


class StaticAnalysisRunner:
    def __init__(
        self,
        analyzers: Sequence[StaticAnalyzer],
        disabled: Sequence[str] = (),
        max_workers: int = 4,
    ) -> None:
        self.analyzers = [a for a in analyzers if a.name not in set(disabled)]
        self.disabled = [a.name for a in analyzers if a.name in set(disabled)]
        self.max_workers = max_workers

    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]:
        jobs: list[tuple[StaticAnalyzer, list[str]]] = []
        runs: list[AnalysisRun] = [
            AnalysisRun(tool=name, status="skipped", detail="disabled in .sentinel.yml")
            for name in self.disabled
        ]
        for analyzer in self.analyzers:
            targets = [f for f in files if detect_language(f) in analyzer.languages]
            if targets:
                jobs.append((analyzer, targets))
        findings: list[Finding] = []
        if not jobs:
            return findings, runs
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [(a, pool.submit(self._safe_run, a, workspace, t)) for a, t in jobs]
            for _, fut in futures:
                out = fut.result()
                runs.append(out.run)
                findings.extend(out.findings)
        return findings, runs

    @staticmethod
    def _safe_run(
        analyzer: StaticAnalyzer, workspace: Path, files: list[str]
    ) -> StaticAnalysisOutput:
        start = time.monotonic()
        try:
            return analyzer.run(workspace, files)
        except Exception as exc:  # an analyzer crash must not sink the review
            return StaticAnalysisOutput(
                AnalysisRun(
                    tool=analyzer.name,
                    status="failed",
                    duration_ms=int((time.monotonic() - start) * 1000),
                    detail=f"{type(exc).__name__}: {exc}"[:300],
                )
            )


def default_analyzers(
    registry: LanguageRegistry | None = None, timeout_s: int = 120
) -> list[StaticAnalyzer]:
    return [
        BuiltinAnalyzer(registry),
        RuffAnalyzer(timeout_s),
        MypyAnalyzer(timeout_s),
        BanditAnalyzer(timeout_s),
        ESLintAnalyzer(timeout_s),
        TscAnalyzer(timeout_s),
    ]
