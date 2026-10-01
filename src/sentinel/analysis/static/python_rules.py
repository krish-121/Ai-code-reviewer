"""Sentinel's own Python rules, implemented as one AST visitor.

Run by ``BuiltinAnalyzer`` (``builtin_security.py``) on every changed Python file. Each
``_check_*`` / ``visit_*`` method below is one rule; the pattern recognisers they rely on
live in ``python_patterns.py`` so the verification probes can reuse them.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from sentinel.analysis.ast.python_analyzer import expr_name
from sentinel.analysis.ast.python_sql import DB_EXEC_METHODS
from sentinel.analysis.static.base import static_finding
from sentinel.analysis.static.python_patterns import (
    BLOCKING_CALLS,
    SQL_SINK_NAMES,
    FunctionNode,
    dynamic_sql_kind,
    function_assignments,
    interpolated_names,
    loop_bodies_with_nested_iteration,
    sql_arg,
)
from sentinel.core.domain.models import Category, Finding, Severity

TOOL = "sentinel"
# Calls that schedule a coroutine instead of awaiting it directly (not a missing await).
SCHEDULERS = frozenset(
    "create_task ensure_future gather wait wait_for run shield as_completed "
    "run_until_complete TaskGroup start_soon".split()
)
UNSAFE_LOADERS = frozenset(
    {
        "pickle.loads",
        "pickle.load",
        "cPickle.loads",
        "marshal.loads",
        "dill.loads",
        "shelve.open",
        "jsonpickle.decode",
    }
)
WEAK_HASHES = frozenset({"md5", "sha1"})
BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})
SHELL_FUNCTIONS = frozenset({"os.system", "os.popen"})
EVAL_FUNCTIONS = frozenset({"eval", "exec"})
SENSITIVE_FUNCTION_NAME = re.compile(r"password|passwd|token|secret|credential|session|auth", re.I)
SELF_PREFIX = "self."


@dataclass
class _Function:
    """The function currently being visited."""

    node: FunctionNode
    assignments: dict[str, ast.AST]
    loops_with_db_reported: set[int] = field(default_factory=set)


class PythonRules(ast.NodeVisitor):
    """Walks one module and collects findings in ``self.findings``."""

    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.functions: list[_Function] = []  # stack: innermost last
        self.loops: list[ast.AST] = []  # loops in the current function, innermost last
        self._reported_sql: set[int] = set()
        self.coroutines = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
        self.module_assignments: dict[str, ast.AST] = {
            target.id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    def add(self, **details: Any) -> None:
        """Record a finding in this file (see ``static_finding`` for the fields)."""
        self.findings.append(static_finding(tool=TOOL, file=self.path, **details))

    @property
    def assignments(self) -> dict[str, ast.AST]:
        """Assignments visible at the current point (function, else module level)."""
        return self.functions[-1].assignments if self.functions else self.module_assignments

    # ------------------------------------------------------------------ scopes
    def _visit_function(self, node: FunctionNode) -> None:
        self.functions.append(_Function(node, function_assignments(node)))
        outer_loops, self.loops = self.loops, []
        self.generic_visit(node)
        self._check_quadratic_loops(node)
        self.loops = outer_loops
        self.functions.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self.loops.append(node)
        self.generic_visit(node)
        self.loops.pop()

    visit_For = _visit_loop
    visit_AsyncFor = _visit_loop
    visit_While = _visit_loop

    # ------------------------------------------------------------------ statements
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Rule ``swallowed-exception``: a broad ``except`` whose body does nothing."""
        broad = node.type is None or expr_name(node.type) in BROAD_EXCEPTIONS
        silent = all(
            isinstance(s, ast.Pass | ast.Continue)
            or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            for s in node.body
        )
        if broad and silent:
            self.add(
                rule="swallowed-exception",
                category=Category.BUG,
                severity=Severity.LOW,
                confidence=0.8,
                line=node.lineno,
                end_line=node.end_lineno,
                title="Exception is caught and silently ignored",
                explanation=(
                    "A broad `except` discards every error, including bugs, without logging. "
                    "Failures become invisible and data can be left half-written."
                ),
                tags=["swallowed-exception"],
                suggested_fix="Catch the specific exception you expect and log or re-raise it.",
            )
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        """Rule ``missing-await``: an ``async def`` of this file called as a bare statement."""
        if isinstance(node.value, ast.Call):
            self._check_missing_await(node, expr_name(node.value.func))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Run every call-based rule on this call."""
        name = expr_name(node.func)
        short = name.split(".")[-1]
        self._check_sql(node, short)
        self._check_code_injection(node, name)
        self._check_command_injection(node, name)
        self._check_deserialization(node, name)
        self._check_tls(node)
        self._check_weak_hash(node, name, short)
        self._check_blocking_in_async(node, name)
        self._check_db_in_loop(node, name, short)
        self.generic_visit(node)

    # ------------------------------------------------------------------ rules
    def _check_quadratic_loops(self, function: FunctionNode) -> None:
        """Rule ``quadratic-loop``: nested loops comparing elements pairwise."""
        for outer, inner in loop_bodies_with_nested_iteration(function):
            same = expr_name(outer.iter) == expr_name(inner.iter) != ""
            self.add(
                rule="quadratic-loop",
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM if same else Severity.LOW,
                confidence=0.75 if same else 0.55,
                line=inner.lineno,
                end_line=inner.end_lineno,
                title="Nested loop compares every pair of elements "
                + ("(O(n²))" if same else "(O(n·m))"),
                explanation=(
                    f"The loop at line {inner.lineno} runs once per element of the loop at "
                    f"line {outer.lineno} and compares elements pairwise. Indexing one side in "
                    "a dict or set makes this linear."
                ),
                tags=["quadratic"],
                suggested_fix="Build a set/dict of one collection once, then do O(1) lookups.",
            )

    def _check_missing_await(self, node: ast.Expr, name: str) -> None:
        short = name.split(".")[-1]
        # Only names we can tie to this file: `f()` or `self.f()`.
        local = name if "." not in name else name.removeprefix(SELF_PREFIX)
        if "." in local or local not in self.coroutines or short in SCHEDULERS:
            return
        self.add(
            rule="missing-await",
            category=Category.BUG,
            severity=Severity.HIGH,
            confidence=0.9,
            line=node.lineno,
            title=f"Coroutine `{short}()` is called but never awaited",
            explanation=(
                f"`{short}` is declared `async def`. Calling it without `await` only "
                "creates a coroutine object; the body never runs."
            ),
            tags=["missing-await", "async"],
            suggested_fix=f"Use `await {name}(...)` (or schedule it with asyncio.create_task).",
        )

    def _check_sql(self, node: ast.Call, short: str) -> None:
        """Rule ``sql-injection``: SQL passed to an execute call is built from strings."""
        if short not in SQL_SINK_NAMES or id(node) in self._reported_sql:
            return
        arg = sql_arg(node)
        if isinstance(arg, ast.Call):  # execute(text(...)): report once, at the outer call
            self._reported_sql.add(id(arg))
        kind = dynamic_sql_kind(arg, self.assignments)
        if not kind:
            return
        names = sorted(interpolated_names(arg, self.assignments))
        values = f" (values: {', '.join(f'`{n}`' for n in names)})" if names else ""
        self.add(
            rule="sql-injection",
            category=Category.SECURITY,
            severity=Severity.HIGH,
            confidence=0.85 if "via" not in kind else 0.75,
            line=node.lineno,
            end_line=node.end_lineno,
            title="SQL query built with string interpolation",
            explanation=(
                f"The SQL passed to `{short}()` is built with {kind}{values}. If any of those "
                "values come from a user, they can change the query (SQL injection)."
            ),
            tags=["sql-injection"],
            suggested_fix="Use a parameterized query: pass values as the second argument "
            "(e.g. `execute('... WHERE name = ?', (name,))`).",
        )

    def _check_code_injection(self, node: ast.Call, name: str) -> None:
        """Rule ``code-injection``: ``eval``/``exec`` on a non-constant value."""
        if name not in EVAL_FUNCTIONS or not _first_arg_is_dynamic(node):
            return
        self.add(
            rule="code-injection",
            category=Category.SECURITY,
            severity=Severity.HIGH,
            confidence=0.8,
            line=node.lineno,
            title=f"`{name}()` on a dynamic value",
            explanation=f"`{name}` executes arbitrary code built at runtime.",
            tags=["code-injection"],
            suggested_fix="Parse the input explicitly (e.g. ast.literal_eval or JSON).",
        )

    def _check_command_injection(self, node: ast.Call, name: str) -> None:
        """Rule ``command-injection``: a shell runs a string built at runtime."""
        uses_shell = name in SHELL_FUNCTIONS or (
            name.startswith("subprocess.") and _keyword_is_true(node, "shell")
        )
        if not uses_shell or not _first_arg_is_dynamic(node):
            return
        self.add(
            rule="command-injection",
            category=Category.SECURITY,
            severity=Severity.HIGH,
            confidence=0.8,
            line=node.lineno,
            title="Shell command built from a variable",
            explanation="Running a shell with a dynamic string allows command injection.",
            tags=["command-injection"],
            suggested_fix="Pass an argument list to subprocess.run without shell=True.",
        )

    def _check_deserialization(self, node: ast.Call, name: str) -> None:
        """Rules ``unsafe-deserialization`` (pickle & co.) and ``unsafe-yaml``."""
        if name in UNSAFE_LOADERS:
            self.add(
                rule="unsafe-deserialization",
                category=Category.SECURITY,
                severity=Severity.HIGH,
                confidence=0.75,
                line=node.lineno,
                title=f"Unsafe deserialization with `{name}`",
                explanation="Deserializing untrusted data with this API can execute code.",
                tags=["deserialization"],
                suggested_fix="Use a data-only format such as JSON, or sign and verify the data.",
            )
        safe_loader = any(k.arg == "Loader" and "Safe" in expr_name(k.value) for k in node.keywords)
        if name == "yaml.load" and not safe_loader:
            self.add(
                rule="unsafe-yaml",
                category=Category.SECURITY,
                severity=Severity.HIGH,
                confidence=0.8,
                line=node.lineno,
                title="yaml.load without SafeLoader",
                explanation="`yaml.load` can construct arbitrary Python objects.",
                tags=["deserialization"],
                suggested_fix="Use `yaml.safe_load`.",
            )

    def _check_tls(self, node: ast.Call) -> None:
        """Rule ``tls-verify-disabled``: ``verify=False``."""
        if not _keyword_is_false(node, "verify"):
            return
        self.add(
            rule="tls-verify-disabled",
            category=Category.SECURITY,
            severity=Severity.MEDIUM,
            confidence=0.9,
            line=node.lineno,
            title="TLS certificate verification disabled",
            explanation="`verify=False` accepts any certificate, enabling MITM attacks.",
            tags=["tls"],
            suggested_fix="Remove `verify=False` or pass a CA bundle path.",
        )

    def _check_weak_hash(self, node: ast.Call, name: str, short: str) -> None:
        """Rule ``weak-hash``: MD5/SHA-1 inside a function about passwords, tokens ..."""
        in_sensitive_function = bool(self.functions) and bool(
            SENSITIVE_FUNCTION_NAME.search(self.functions[-1].node.name)
        )
        if short not in WEAK_HASHES or not name.startswith("hashlib") or not in_sensitive_function:
            return
        self.add(
            rule="weak-hash",
            category=Category.SECURITY,
            severity=Severity.MEDIUM,
            confidence=0.75,
            line=node.lineno,
            title=f"Weak hash `{short}` used for sensitive data",
            explanation="MD5/SHA-1 are fast and broken; unsuitable for passwords or tokens.",
            tags=["weak-crypto"],
            suggested_fix="Use a password hash (bcrypt/argon2/scrypt) or hmac with SHA-256.",
        )

    def _check_blocking_in_async(self, node: ast.Call, name: str) -> None:
        """Rule ``blocking-in-async``: e.g. ``time.sleep`` or ``requests.get`` in ``async def``."""
        function = self.functions[-1].node if self.functions else None
        label = BLOCKING_CALLS.get(name)
        if not isinstance(function, ast.AsyncFunctionDef) or label is None:
            return
        self.add(
            rule="blocking-in-async",
            category=Category.PERFORMANCE,
            severity=Severity.MEDIUM,
            confidence=0.85,
            line=node.lineno,
            title=f"Blocking call {label} inside async function",
            explanation=(
                f"`{function.name}` is `async`, but {label} blocks the event "
                "loop: every other request on this worker stalls until it returns."
            ),
            tags=["blocking-in-async", "async"],
            suggested_fix="Use the async equivalent (asyncio.sleep, httpx.AsyncClient, an async "
            "DB driver) or run it in a thread with asyncio.to_thread.",
        )

    def _check_db_in_loop(self, node: ast.Call, name: str, short: str) -> None:
        """Rule ``n-plus-one``: a query inside a loop (reported once per loop)."""
        if not self.loops or not self.functions or short not in DB_EXEC_METHODS:
            return
        loop = self.loops[-1]
        function = self.functions[-1]
        if id(loop) in function.loops_with_db_reported:
            return
        function.loops_with_db_reported.add(id(loop))
        self.add(
            rule="n-plus-one",
            category=Category.PERFORMANCE,
            severity=Severity.MEDIUM,
            confidence=0.75,
            line=node.lineno,
            title="Database query inside a loop (N+1 queries)",
            explanation=(
                f"`{name}()` runs once per iteration of the loop at line "
                f"{getattr(loop, 'lineno', '?')}. With N rows this issues N+1 round trips."
            ),
            tags=["n+1"],
            suggested_fix="Fetch all rows in one query (JOIN or `WHERE id IN (...)`) before "
            "the loop.",
        )


def _first_arg_is_dynamic(node: ast.Call) -> bool:
    return bool(node.args) and not isinstance(node.args[0], ast.Constant)


def _keyword_is_true(node: ast.Call, name: str) -> bool:
    return any(
        k.arg == name and isinstance(k.value, ast.Constant) and bool(k.value.value)
        for k in node.keywords
    )


def _keyword_is_false(node: ast.Call, name: str) -> bool:
    return any(
        k.arg == name and isinstance(k.value, ast.Constant) and k.value.value is False
        for k in node.keywords
    )
