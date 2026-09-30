"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.graph.builder import GraphBuildResult, build_graph

FIXTURES = Path(__file__).parent / "fixtures"
SHOP = FIXTURES / "shop"


def read_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(part.startswith((".", "__pycache__")) for part in p.parts)
    }


def build_shop() -> tuple[dict[str, str], GraphBuildResult]:
    sources = read_tree(SHOP)
    symbols = default_registry().analyze(sources)
    return sources, build_graph(symbols)
