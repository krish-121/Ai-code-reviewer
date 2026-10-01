"""SQL-injection probe: is the cited query really built from strings, and from what?

Python is checked on the AST (``python_patterns``); JavaScript/TypeScript with narrow
regular expressions around the cited lines. A parameterized query is a *decisive*
contradiction: no amount of AI confidence can make it injectable.
"""

from __future__ import annotations

import ast
import re

from sentinel.analysis.ast.python_analyzer import expr_name
from sentinel.analysis.static.probes.common import (
    HIGH_WEIGHT,
    LOW_WEIGHT,
    VERY_HIGH_WEIGHT,
    python_tree,
    result,
)
from sentinel.analysis.static.python_patterns import (
    FunctionNode,
    calls_in_lines,
    dynamic_sql_kind,
    enclosing_function,
    function_assignments,
    interpolated_names,
    is_parameterized,
    is_sql_sink,
    sql_arg,
)
from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext, reachability

CAST_FUNCTIONS = frozenset({"int", "float", "bool", "uuid.UUID", "UUID", "Decimal"})
NEARBY_LINES = 2  # AI citations are often a line or two off
JS_TAGGED_TEMPLATE = re.compile(r"(\$queryRaw|\bsql)\s*`")
JS_INTERPOLATED = (
    re.compile(r"\.(query|execute|raw\w*)\s*\(\s*`[^`]*\$\{"),
    re.compile(r"\.(query|execute)\s*\(\s*['\"][^'\"]*['\"]\s*\+"),
)
JS_PLACEHOLDERS = re.compile(r"\.(query|execute)\s*\([^)]*(\$\d|\?)[^)]*,\s*\[")


class SqlInjectionProbe:
    """Confirms or refutes findings tagged ``sql-injection``."""

    name = "probe:sql-injection"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Look at the SQL calls on (or next to) the cited lines."""
        if "sql-injection" not in finding.tags:
            return None
        tree = python_tree(finding, ctx)
        if tree is None:
            return self._check_javascript(finding, ctx)
        first, last = finding.line_start - NEARBY_LINES, finding.line_end + NEARBY_LINES
        sinks = [c for c in calls_in_lines(tree, first, last) if is_sql_sink(c)]
        if not sinks:
            detail = "no SQL execution call at the cited lines"
            return result(self.name, CheckOutcome.CONTRADICTS, detail, LOW_WEIGHT)
        function = enclosing_function(tree, sinks[0].lineno)
        for call in sinks:
            verdict = self._check_dynamic_call(call, function, finding, ctx)
            if verdict is not None:
                return verdict
        if all(is_parameterized(c) for c in sinks):
            detail = "the query is parameterized (placeholders + a separate parameters argument)"
            return result(
                self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
            )
        detail = "the SQL argument is a constant string"
        return result(self.name, CheckOutcome.CONTRADICTS, detail, HIGH_WEIGHT, decisive=True)

    def _check_dynamic_call(
        self,
        call: ast.Call,
        function: FunctionNode | None,
        finding: Finding,
        ctx: VerificationContext,
    ) -> VerificationCheck | None:
        """Verdict for one SQL call whose text is built dynamically (None if it is not)."""
        assignments = function_assignments(function) if function else {}
        argument = sql_arg(call)
        kind = dynamic_sql_kind(argument, assignments)
        if not kind:
            return None
        direct = _directly_interpolated(argument, assignments)
        cast = {name for name in direct if _is_cast(assignments.get(name))}
        if direct and cast == direct:
            detail = (
                f"interpolated values ({', '.join(sorted(cast))}) are cast with "
                "int()/float() first, so they cannot carry SQL"
            )
            return result(self.name, CheckOutcome.CONTRADICTS, detail, HIGH_WEIGHT)
        parameters = {p.arg for p in function.args.args} if function else set()
        tainted = sorted(interpolated_names(argument, assignments) & parameters)
        detail = f"SQL passed to `{expr_name(call.func)}()` is built with {kind}"
        if tainted:
            detail += f"; `{'`, `'.join(tainted)}` come from the function's parameters"
            label, path = reachability(finding, ctx)
            if label == "entrypoint":
                detail += f", reachable from {path[0]}"
        return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)

    def _check_javascript(
        self, finding: Finding, ctx: VerificationContext
    ) -> VerificationCheck | None:
        start = max(0, finding.line_start - NEARBY_LINES - 1)
        text = "\n".join(ctx.lines(finding.file)[start : finding.line_end + NEARBY_LINES])
        if JS_TAGGED_TEMPLATE.search(text):
            detail = "tagged-template query: values are sent as parameters"
            return result(
                self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
            )
        if any(pattern.search(text) for pattern in JS_INTERPOLATED):
            detail = "query text is built by string interpolation"
            return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        if JS_PLACEHOLDERS.search(text):
            detail = "query uses placeholders with a values array"
            return result(
                self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
            )
        return None


def _directly_interpolated(node: ast.AST | None, assignments: dict[str, ast.AST]) -> set[str]:
    """Names interpolated directly into the SQL text (one assignment hop for the query)."""
    if isinstance(node, ast.Name) and isinstance(
        assignments.get(node.id), ast.JoinedStr | ast.BinOp | ast.Call
    ):
        node = assignments[node.id]
    parts: list[ast.AST] = []
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
    elif isinstance(node, ast.BinOp):
        parts = [node.left, node.right]
    elif isinstance(node, ast.Call):
        parts = list(node.args)
    return {p.id for p in parts if isinstance(p, ast.Name)}


def _is_cast(node: ast.AST | None) -> bool:
    """``int(x)``, ``UUID(x)`` ...: the value can no longer carry SQL syntax."""
    return isinstance(node, ast.Call) and expr_name(node.func) in CAST_FUNCTIONS
