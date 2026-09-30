"""Deterministic verification probes.

A probe looks at the exact code a finding cites and answers a narrow question with an
AST or the extracted symbols: *is this query actually parameterized? is this function
actually async? is there really a query inside that loop?* Probes are where most
confident rejections come from — they turn "the AI said so" into "the code shows so".
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache

from sentinel.analysis.ast.python_analyzer import expr_name
from sentinel.analysis.diff.secrets import scan_line
from sentinel.analysis.static.builtin_security import (
    BLOCKING_CALLS,
    calls_in_lines,
    dynamic_sql_kind,
    enclosing_function,
    function_assignments,
    interpolated_names,
    is_parameterized,
    is_sql_sink,
    loop_bodies_with_nested_iteration,
    parse_python,
    sql_arg,
)
from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext, Verifier, reachability

AUTHZ_RE = re.compile(
    r"\b(is_admin|is_superuser|has_perm\w*|has_role|require_role|authorize\w*|"
    r"check_permission\w*|can_access|is_owner|ensure_admin|isAdmin|hasPermission|hasRole)\b"
)
AUTHN_RE = re.compile(
    r"\b(authenticate\w*|verify_token|decode_token|validate_token|get_current_user|"
    r"login_required|verify_jwt|jwt\.decode|verify_password|check_password|verifyToken|"
    r"authenticateUser|requireAuth|getCurrentUser)\b"
)
ENV_READ_RE = re.compile(r"os\.environ|os\.getenv|getenv\(|process\.env|config\[|settings\.")
CAST_FUNCS = {"int", "float", "bool", "uuid.UUID", "UUID", "Decimal"}


@lru_cache(maxsize=128)
def _tree(source: str) -> ast.Module | None:
    return parse_python(source)


def _py(finding: Finding, ctx: VerificationContext) -> ast.Module | None:
    if not finding.file.endswith((".py", ".pyi")):
        return None
    source = ctx.sources.get(finding.file)
    return _tree(source) if source else None


def _check(
    name: str, outcome: CheckOutcome, detail: str, weight: float = 1.0, decisive: bool = False
) -> VerificationCheck:
    return VerificationCheck(
        name=name, outcome=outcome, detail=detail, weight=weight, decisive=decisive
    )


class SqlInjectionProbe:
    name = "probe:sql-injection"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if "sql-injection" not in finding.tags:
            return None
        tree = _py(finding, ctx)
        if tree is None:
            return self._js(finding, ctx)
        sinks = [
            c
            for c in calls_in_lines(tree, finding.line_start - 2, finding.line_end + 2)
            if is_sql_sink(c)
        ]
        if not sinks:
            return _check(
                self.name, CheckOutcome.CONTRADICTS, "no SQL execution call at the cited lines", 1.0
            )
        fn = enclosing_function(tree, sinks[0].lineno)
        assignments = function_assignments(fn) if fn else {}
        for call in sinks:
            kind = dynamic_sql_kind(sql_arg(call), assignments)
            if not kind:
                continue
            names = interpolated_names(sql_arg(call), assignments)
            direct = _direct_names(sql_arg(call), assignments)
            cast = {n for n in direct if _is_cast(assignments.get(n))}
            if direct and cast == direct:
                return _check(
                    self.name,
                    CheckOutcome.CONTRADICTS,
                    f"interpolated values ({', '.join(sorted(cast))}) are cast with "
                    "int()/float() first, so they cannot carry SQL",
                    1.5,
                )
            params = {p.arg for p in fn.args.args} if fn else set()
            tainted = sorted(names & params)
            detail = f"SQL passed to `{expr_name(call.func)}()` is built with {kind}"
            if tainted:
                detail += f"; `{'`, `'.join(tainted)}` come from the function's parameters"
                label, path = reachability(finding, ctx)
                if label == "entrypoint":
                    detail += f", reachable from {path[0]}"
            return _check(self.name, CheckOutcome.SUPPORTS, detail, 2.0)
        if all(is_parameterized(c) for c in sinks):
            return _check(
                self.name,
                CheckOutcome.CONTRADICTS,
                "the query is parameterized (placeholders + a separate parameters argument)",
                2.0,
                decisive=True,
            )
        return _check(
            self.name,
            CheckOutcome.CONTRADICTS,
            "the SQL argument is a constant string",
            1.5,
            decisive=True,
        )

    def _js(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        lines = ctx.lines(finding.file)[max(0, finding.line_start - 3) : finding.line_end + 2]
        blob = "\n".join(lines)
        if re.search(r"(\$queryRaw|\bsql)\s*`", blob):
            return _check(
                self.name,
                CheckOutcome.CONTRADICTS,
                "tagged-template query: values are sent as parameters",
                2.0,
                decisive=True,
            )
        if re.search(r"\.(query|execute|raw\w*)\s*\(\s*`[^`]*\$\{", blob) or re.search(
            r"\.(query|execute)\s*\(\s*['\"][^'\"]*['\"]\s*\+", blob
        ):
            return _check(
                self.name, CheckOutcome.SUPPORTS, "query text is built by string interpolation", 2.0
            )
        if re.search(r"\.(query|execute)\s*\([^)]*(\$\d|\?)[^)]*,\s*\[", blob):
            return _check(
                self.name,
                CheckOutcome.CONTRADICTS,
                "query uses placeholders with a values array",
                2.0,
                decisive=True,
            )
        return None


def _direct_names(node: ast.AST | None, assignments: dict[str, ast.AST]) -> set[str]:
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
    return isinstance(node, ast.Call) and expr_name(node.func) in CAST_FUNCS


class NPlusOneProbe:
    name = "probe:n+1"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if "n+1" not in finding.tags:
            return None
        fs = ctx.symbols.get(finding.file)
        node = ctx.enclosing(finding)
        if fs is None or node is None:
            return None
        lo, hi = node.line_start or 0, node.line_end or 0
        ops = [o for o in fs.db_operations if lo <= o.line <= hi]
        in_loop = [o for o in ops if o.in_loop]
        if in_loop:
            return _check(
                self.name,
                CheckOutcome.SUPPORTS,
                f"`{in_loop[0].detail}` at line {in_loop[0].line} runs inside a loop "
                f"in `{node.name}`",
                2.0,
            )
        if ops:
            return _check(
                self.name,
                CheckOutcome.CONTRADICTS,
                f"`{node.name}` queries the database, but not inside a loop",
                1.5,
            )
        return _check(
            self.name, CheckOutcome.CONTRADICTS, f"no database access found in `{node.name}`", 1.0
        )


class AsyncProbe:
    name = "probe:async"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        tags = set(finding.tags)
        if not tags & {"blocking-in-async", "missing-await"}:
            return None
        tree = _py(finding, ctx)
        if tree is None:
            return None
        fn = enclosing_function(tree, finding.line_start)
        if fn is None:
            return None
        if "blocking-in-async" in tags:
            if not isinstance(fn, ast.AsyncFunctionDef):
                return _check(
                    self.name,
                    CheckOutcome.CONTRADICTS,
                    f"`{fn.name}` is not async, so it cannot block an event loop",
                    2.0,
                    decisive=True,
                )
            blocking = [
                c
                for c in ast.walk(fn)
                if isinstance(c, ast.Call) and expr_name(c.func) in BLOCKING_CALLS
            ]
            if blocking:
                call = blocking[0]
                return _check(
                    self.name,
                    CheckOutcome.SUPPORTS,
                    f"`{expr_name(call.func)}()` at line {call.lineno} is synchronous "
                    f"inside async `{fn.name}`",
                    2.0,
                )
            return None
        # missing-await
        awaited = {id(n.value) for n in ast.walk(fn) if isinstance(n, ast.Await)}
        calls = calls_in_lines(fn, finding.line_start, finding.line_end)
        coroutines = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
        for call in calls:
            name = expr_name(call.func).split(".")[-1]
            if name in coroutines:
                if id(call) in awaited:
                    return _check(
                        self.name,
                        CheckOutcome.CONTRADICTS,
                        f"`{name}()` is awaited at line {call.lineno}",
                        2.0,
                        decisive=True,
                    )
                return _check(
                    self.name,
                    CheckOutcome.SUPPORTS,
                    f"`{name}` is async and the call at line {call.lineno} is not awaited",
                    2.0,
                )
        return None


class QuadraticProbe:
    name = "probe:quadratic"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if "quadratic" not in finding.tags:
            return None
        tree = _py(finding, ctx)
        if tree is None:
            return None
        fn = enclosing_function(tree, finding.line_start)
        if fn is None:
            return None
        pairs = loop_bodies_with_nested_iteration(fn)
        if pairs:
            outer, inner = pairs[0]
            return _check(
                self.name,
                CheckOutcome.SUPPORTS,
                f"loop at line {inner.lineno} is nested in the loop at line "
                f"{outer.lineno} and compares their elements",
                2.0,
            )
        has_nested = any(
            isinstance(n, ast.For)
            and any(isinstance(m, ast.For) and m is not n for m in ast.walk(n))
            for n in ast.walk(fn)
        )
        if not has_nested:
            return _check(
                self.name, CheckOutcome.CONTRADICTS, f"`{fn.name}` contains no nested loops", 1.5
            )
        return None


class SecretProbe:
    name = "probe:secret"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if "secret" not in finding.tags:
            return None
        lines = ctx.lines(finding.file)
        exact = range(max(1, finding.line_start), min(len(lines), finding.line_end) + 1)
        for n in exact:
            if scan_line(lines[n - 1], n):
                return _check(
                    self.name,
                    CheckOutcome.SUPPORTS,
                    f"line {n} contains a credential-shaped literal",
                    2.0,
                )
        cited = lines[finding.line_start - 1] if 0 < finding.line_start <= len(lines) else ""
        if ENV_READ_RE.search(cited):
            return _check(
                self.name,
                CheckOutcome.CONTRADICTS,
                "the value is read from the environment/configuration, not hard-coded",
                2.0,
                decisive=True,
            )
        for n in (finding.line_start - 1, finding.line_end + 1):  # tolerate off-by-one citations
            if 0 < n <= len(lines) and scan_line(lines[n - 1], n):
                return _check(
                    self.name,
                    CheckOutcome.SUPPORTS,
                    f"line {n} contains a credential-shaped literal",
                    1.5,
                )
        return None


class AuthOrderProbe:
    name = "probe:auth"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if "auth" not in finding.tags:
            return None
        node = ctx.enclosing(finding)
        if node is None or node.line_start is None or node.line_end is None:
            return None
        lines = ctx.lines(finding.file)[node.line_start - 1 : node.line_end]
        authz = _first_line(lines, AUTHZ_RE, node.line_start)
        authn = _first_line(lines, AUTHN_RE, node.line_start)
        text = f"{finding.title} {finding.explanation}".lower()
        if "before" in text or "order" in text or "prior to" in text:
            if authz and authn:
                if authz[0] < authn[0]:
                    return _check(
                        self.name,
                        CheckOutcome.SUPPORTS,
                        f"`{authz[1]}` (line {authz[0]}) runs before `{authn[1]}` "
                        f"(line {authn[0]})",
                        2.0,
                    )
                return _check(
                    self.name,
                    CheckOutcome.CONTRADICTS,
                    f"`{authn[1]}` (line {authn[0]}) already runs before `{authz[1]}` "
                    f"(line {authz[0]})",
                    2.0,
                    decisive=True,
                )
            return None
        if re.search(r"missing|no (authori|auth|permission)|without (authori|auth|checking)", text):
            path_nodes = [node]
            label, _ = reachability(finding, ctx)
            path = ctx.graph.path_from_entrypoint(node.id) or []
            path_nodes.extend(n for n in path if n.file and n.line_start and n.line_end)
            for n in path_nodes:
                src = ctx.lines(n.file or "")[(n.line_start or 1) - 1 : n.line_end or 0]
                hit = _first_line(src, AUTHZ_RE, n.line_start or 1)
                if hit:
                    return _check(
                        self.name,
                        CheckOutcome.CONTRADICTS,
                        f"authorization is checked by `{hit[1]}` in `{n.name}` (line {hit[0]})",
                        1.5,
                    )
            if label == "entrypoint":
                return _check(
                    self.name,
                    CheckOutcome.SUPPORTS,
                    "no authorization check on the path from the entry point",
                    1.5,
                )
        return None


def _first_line(lines: list[str], pattern: re.Pattern[str], offset: int) -> tuple[int, str] | None:
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("#", "//")):
            continue
        m = pattern.search(line)
        if m:
            return offset + i, m.group(1)
    return None


class ErrorHandlingProbe:
    name = "probe:error-handling"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        if not set(finding.tags) & {"swallowed-exception", "missing-error-handling"}:
            return None
        tree = _py(finding, ctx)
        if tree is None:
            return None
        lo, hi = finding.line_start - 2, finding.line_end + 2
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            end = node.end_lineno or node.lineno
            if not (node.lineno <= hi and lo <= end):
                continue
            for handler in node.handlers:
                silent = all(isinstance(s, ast.Pass | ast.Continue) for s in handler.body)
                if silent:
                    return _check(
                        self.name,
                        CheckOutcome.SUPPORTS,
                        f"exception handler at line {handler.lineno} discards the error",
                        2.0,
                    )
            if "missing-error-handling" in finding.tags and node.handlers:
                return _check(
                    self.name,
                    CheckOutcome.CONTRADICTS,
                    f"the cited code is inside a try block with a handler at line "
                    f"{node.handlers[0].lineno}",
                    1.25,
                )
        return None


def default_probes() -> list[Verifier]:
    return [
        SqlInjectionProbe(),
        NPlusOneProbe(),
        AsyncProbe(),
        QuadraticProbe(),
        SecretProbe(),
        AuthOrderProbe(),
        ErrorHandlingProbe(),
    ]
