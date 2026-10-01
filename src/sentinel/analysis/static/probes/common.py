"""Helpers shared by the probes: building check results, parsing, finding lines."""

from __future__ import annotations

import ast
import re
from functools import lru_cache

from sentinel.analysis.static.python_patterns import parse_python
from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext

# How much one probe result counts in the verifier's score. The engine treats support
# with a weight of at least ``engine.STRONG_WEIGHT`` (1.5) as strong evidence.
LOW_WEIGHT = 1.0
MODERATE_WEIGHT = 1.25
HIGH_WEIGHT = 1.5
VERY_HIGH_WEIGHT = 2.0
PYTHON_SUFFIXES = (".py", ".pyi")
COMMENT_PREFIXES = ("#", "//")
PARSE_CACHE_SIZE = 128


def result(
    name: str,
    outcome: CheckOutcome,
    detail: str,
    weight: float = LOW_WEIGHT,
    *,
    decisive: bool = False,
) -> VerificationCheck:
    """The ``VerificationCheck`` a probe returns."""
    return VerificationCheck(
        name=name, outcome=outcome, detail=detail, weight=weight, decisive=decisive
    )


def python_tree(finding: Finding, ctx: VerificationContext) -> ast.Module | None:
    """The parsed module the finding points at (None for other languages or bad syntax)."""
    if not finding.file.endswith(PYTHON_SUFFIXES):
        return None
    source = ctx.sources.get(finding.file)
    return _parse(source) if source else None


@lru_cache(maxsize=PARSE_CACHE_SIZE)
def _parse(source: str) -> ast.Module | None:
    """Parse once per source text: several probes look at the same file."""
    return parse_python(source)


def first_match(
    lines: list[str], pattern: re.Pattern[str], first_line_number: int
) -> tuple[int, str] | None:
    """``(line number, matched text)`` of the first non-comment line matching ``pattern``."""
    for index, line in enumerate(lines):
        if line.lstrip().startswith(COMMENT_PREFIXES):
            continue
        match = pattern.search(line)
        if match:
            return first_line_number + index, match.group(1)
    return None
