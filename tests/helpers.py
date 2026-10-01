"""Shared test helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.graph.builder import GraphBuildResult, build_graph
from sentinel.infrastructure.database.models import Base
from sentinel.infrastructure.database.session import Database

FIXTURES = Path(__file__).parent / "fixtures"
SHOP = FIXTURES / "shop"

# Tests that take a ``backend`` parameter run on SQLite, and on PostgreSQL too when
# SENTINEL_TEST_DATABASE_URL points at a (disposable) PostgreSQL database.
POSTGRES_URL = os.environ.get("SENTINEL_TEST_DATABASE_URL")
DATABASE_BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def fresh_database_url(backend: str, tmp_path: Path) -> str:
    """URL of an empty database for ``backend``; skips the test if PostgreSQL isn't configured."""
    if backend == "sqlite":
        return f"sqlite:///{tmp_path}/test.db"
    if not POSTGRES_URL:
        pytest.skip("set SENTINEL_TEST_DATABASE_URL to run against PostgreSQL")
    database = Database(POSTGRES_URL)
    Base.metadata.drop_all(database.engine)
    database.engine.dispose()
    return POSTGRES_URL


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
