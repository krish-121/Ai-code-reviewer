"""Trusted Docker entry point for analysis of a mounted scratch workspace."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
from sentinel.core.paths import relative_file
from sentinel.sandbox.analysis import AnalysisReport


def main() -> None:
    """Parse fixed-position arguments and print one schema-validated analysis report."""
    files = [relative_file(path) for path in json.loads(sys.argv[1])]
    disabled = json.loads(sys.argv[2])
    timeout = int(sys.argv[3])
    registry = default_registry(search_roots=())
    runner = StaticAnalysisRunner(
        default_analyzers(registry, timeout_s=timeout, trust_workspace=False), disabled=disabled
    )
    findings, runs = runner.run(Path.cwd(), files)
    print(AnalysisReport(findings=findings, runs=runs).model_dump_json())


if __name__ == "__main__":
    main()
