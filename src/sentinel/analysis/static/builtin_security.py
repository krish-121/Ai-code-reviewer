"""Sentinel's own deterministic rules, packaged as a ``StaticAnalyzer``.

These cover the patterns the verifier most often needs to confirm or refute (SQL built
from strings, shell/eval injection, unsafe deserialization, blocking calls in async
code, coroutines that are never awaited, database access inside loops, quadratic
nested loops, swallowed exceptions). They run without any external tool installed.

Registered in ``runner.default_analyzers``. The rules themselves live in
``python_rules.py`` and ``js_rules.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

from sentinel.analysis.ast.registry import LanguageRegistry
from sentinel.analysis.static.js_rules import js_rule_findings, symbols_db_in_loop
from sentinel.analysis.static.python_patterns import parse_python
from sentinel.analysis.static.python_rules import PythonRules
from sentinel.core.domain.models import AnalysisRun, Finding, Language, ToolStatus
from sentinel.core.domain.ports import StaticAnalysisOutput

PYTHON_SUFFIXES = (".py", ".pyi")


class BuiltinAnalyzer:
    """Runs the built-in Python and JS/TS rules on the changed files."""

    name = "sentinel"
    languages = frozenset({Language.PYTHON, Language.TYPESCRIPT, Language.JAVASCRIPT})

    def __init__(self, registry: LanguageRegistry | None = None) -> None:
        self.registry = registry  # used to find N+1 patterns in JS/TS via FileSymbols

    def is_available(self) -> bool:
        """Always available: no external tool is needed."""
        return True

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        """Analyze ``files`` (paths relative to ``workspace``)."""
        start = time.monotonic()
        findings: list[Finding] = []
        js_sources: dict[str, str] = {}
        for rel in files:
            try:
                source = (workspace / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            findings.extend(self.analyze_source(rel, source))
            if not rel.endswith(PYTHON_SUFFIXES):
                js_sources[rel] = source
        if js_sources and self.registry is not None:
            for fs in self.registry.analyze(js_sources).values():
                findings.extend(symbols_db_in_loop(fs))
        run = AnalysisRun(
            tool=self.name,
            status=ToolStatus.OK,
            findings=len(findings),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return StaticAnalysisOutput(run, findings)

    @staticmethod
    def analyze_source(path: str, source: str) -> list[Finding]:
        """Findings for one file's source text."""
        if not path.endswith(PYTHON_SUFFIXES):
            return js_rule_findings(path, source)
        tree = parse_python(source)
        if tree is None:
            return []
        rules = PythonRules(path, tree)
        rules.visit(tree)
        return rules.findings
