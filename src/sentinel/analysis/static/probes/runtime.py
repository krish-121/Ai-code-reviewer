"""Probes for runtime behaviour: async misuse, N+1 queries, quadratic loops, error handling."""

from __future__ import annotations

import ast

from sentinel.analysis.ast.python_analyzer import expr_name
from sentinel.analysis.static.probes.common import (
    HIGH_WEIGHT,
    LOW_WEIGHT,
    MODERATE_WEIGHT,
    VERY_HIGH_WEIGHT,
    python_tree,
    result,
)
from sentinel.analysis.static.python_patterns import (
    BLOCKING_CALLS,
    FunctionNode,
    calls_in_lines,
    enclosing_function,
    loop_bodies_with_nested_iteration,
)
from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext

NEARBY_LINES = 2
ASYNC_TAGS = frozenset({"blocking-in-async", "missing-await"})
ERROR_HANDLING_TAGS = frozenset({"swallowed-exception", "missing-error-handling"})


class NPlusOneProbe:
    """Is there really a database query inside a loop in the cited function?"""

    name = "probe:n+1"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Use the ``DbOperation``s the language analyzer recorded for the function."""
        if "n+1" not in finding.tags:
            return None
        symbols = ctx.symbols.get(finding.file)
        node = ctx.enclosing(finding)
        if symbols is None or node is None:
            return None
        first, last = node.line_start or 0, node.line_end or 0
        operations = [o for o in symbols.db_operations if first <= o.line <= last]
        in_loop = [o for o in operations if o.in_loop]
        if in_loop:
            detail = (
                f"`{in_loop[0].detail}` at line {in_loop[0].line} runs inside a loop "
                f"in `{node.name}`"
            )
            return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        if operations:
            detail = f"`{node.name}` queries the database, but not inside a loop"
            return result(self.name, CheckOutcome.CONTRADICTS, detail, HIGH_WEIGHT)
        detail = f"no database access found in `{node.name}`"
        return result(self.name, CheckOutcome.CONTRADICTS, detail, LOW_WEIGHT)


class AsyncProbe:
    """Blocking calls in ``async def`` and coroutines that are never awaited."""

    name = "probe:async"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Inspect the function enclosing the cited line."""
        tags = set(finding.tags)
        if not tags & ASYNC_TAGS:
            return None
        tree = python_tree(finding, ctx)
        function = enclosing_function(tree, finding.line_start) if tree else None
        if tree is None or function is None:
            return None
        if "blocking-in-async" in tags:
            return self._check_blocking(function)
        return self._check_missing_await(tree, function, finding)

    def _check_blocking(self, function: FunctionNode) -> VerificationCheck | None:
        if not isinstance(function, ast.AsyncFunctionDef):
            detail = f"`{function.name}` is not async, so it cannot block an event loop"
            return result(
                self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
            )
        blocking = [
            c
            for c in ast.walk(function)
            if isinstance(c, ast.Call) and expr_name(c.func) in BLOCKING_CALLS
        ]
        if not blocking:
            return None
        call = blocking[0]
        detail = (
            f"`{expr_name(call.func)}()` at line {call.lineno} is synchronous "
            f"inside async `{function.name}`"
        )
        return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)

    def _check_missing_await(
        self, tree: ast.Module, function: FunctionNode, finding: Finding
    ) -> VerificationCheck | None:
        awaited = {id(n.value) for n in ast.walk(function) if isinstance(n, ast.Await)}
        coroutines = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
        for call in calls_in_lines(function, finding.line_start, finding.line_end):
            name = expr_name(call.func).split(".")[-1]
            if name not in coroutines:
                continue
            if id(call) in awaited:
                detail = f"`{name}()` is awaited at line {call.lineno}"
                return result(
                    self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
                )
            detail = f"`{name}` is async and the call at line {call.lineno} is not awaited"
            return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        return None


class QuadraticProbe:
    """Does the cited function really compare every pair of elements in nested loops?"""

    name = "probe:quadratic"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Look for nested loops over collections that compare their elements."""
        if "quadratic" not in finding.tags:
            return None
        tree = python_tree(finding, ctx)
        function = enclosing_function(tree, finding.line_start) if tree else None
        if function is None:
            return None
        pairs = loop_bodies_with_nested_iteration(function)
        if pairs:
            outer, inner = pairs[0]
            detail = (
                f"loop at line {inner.lineno} is nested in the loop at line "
                f"{outer.lineno} and compares their elements"
            )
            return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        if not _has_nested_for_loop(function):
            detail = f"`{function.name}` contains no nested loops"
            return result(self.name, CheckOutcome.CONTRADICTS, detail, HIGH_WEIGHT)
        return None


class ErrorHandlingProbe:
    """Swallowed exceptions, and claims that an error is not handled."""

    name = "probe:error-handling"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Inspect ``try`` blocks overlapping the cited lines."""
        if not set(finding.tags) & ERROR_HANDLING_TAGS:
            return None
        tree = python_tree(finding, ctx)
        if tree is None:
            return None
        first, last = finding.line_start - NEARBY_LINES, finding.line_end + NEARBY_LINES
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not (node.lineno <= last and first <= (node.end_lineno or node.lineno)):
                continue
            verdict = self._check_try(node, finding)
            if verdict is not None:
                return verdict
        return None

    def _check_try(self, node: ast.Try, finding: Finding) -> VerificationCheck | None:
        for handler in node.handlers:
            if all(isinstance(s, ast.Pass | ast.Continue) for s in handler.body):
                detail = f"exception handler at line {handler.lineno} discards the error"
                return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        if "missing-error-handling" in finding.tags and node.handlers:
            detail = (
                "the cited code is inside a try block with a handler at line "
                f"{node.handlers[0].lineno}"
            )
            return result(self.name, CheckOutcome.CONTRADICTS, detail, MODERATE_WEIGHT)
        return None


def _has_nested_for_loop(function: FunctionNode) -> bool:
    return any(
        isinstance(outer, ast.For)
        and any(isinstance(inner, ast.For) and inner is not outer for inner in ast.walk(outer))
        for outer in ast.walk(function)
    )
