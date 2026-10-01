"""Sentinel's own deterministic rules.

These cover the patterns the verifier most often needs to confirm or refute (SQL built
from strings, shell/eval injection, unsafe deserialization, blocking calls in async
code, coroutines that are never awaited, database access inside loops, quadratic
nested loops, swallowed exceptions). They run without any external tool installed, and
the AST helpers here are reused by the verification probes.
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.analysis.ast.python_analyzer import DB_EXEC_METHODS, expr_name
from sentinel.analysis.ast.registry import LanguageRegistry
from sentinel.analysis.static.base import static_finding
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.models import (
    AnalysisRun,
    Category,
    Finding,
    Language,
    Severity,
    ToolStatus,
)
from sentinel.core.domain.ports import StaticAnalysisOutput

TOOL = "sentinel"
SQL_SINK_NAMES = DB_EXEC_METHODS | {"text"}
PLACEHOLDER_RE = re.compile(r"(%s|\?|:\w+|\$\d+|%\(\w+\)s)")
BLOCKING_CALLS = {
    "time.sleep": "time.sleep()",
    "requests.get": "requests (synchronous HTTP)",
    "requests.post": "requests (synchronous HTTP)",
    "requests.put": "requests (synchronous HTTP)",
    "requests.delete": "requests (synchronous HTTP)",
    "requests.patch": "requests (synchronous HTTP)",
    "requests.request": "requests (synchronous HTTP)",
    "urllib.request.urlopen": "urllib (synchronous HTTP)",
    "subprocess.run": "subprocess.run()",
    "subprocess.call": "subprocess.call()",
    "subprocess.check_output": "subprocess.check_output()",
    "os.system": "os.system()",
    "sqlite3.connect": "sqlite3 (synchronous database)",
}
SCHEDULERS = {
    "create_task",
    "ensure_future",
    "gather",
    "wait",
    "wait_for",
    "run",
    "shield",
    "as_completed",
    "run_until_complete",
    "TaskGroup",
    "start_soon",
}
UNSAFE_LOADERS = {
    "pickle.loads",
    "pickle.load",
    "cPickle.loads",
    "marshal.loads",
    "dill.loads",
    "shelve.open",
    "jsonpickle.decode",
}
SENSITIVE_FN = re.compile(r"password|passwd|token|secret|credential|session|auth", re.I)


# --------------------------------------------------------------------------- helpers


def dynamic_sql_kind(
    node: ast.AST | None, assignments: dict[str, ast.AST] | None = None, depth: int = 0
) -> str | None:
    """How a SQL argument is built dynamically, or None if it is a constant."""
    if node is None or depth > 4:
        return None
    if isinstance(node, ast.JoinedStr):
        return "f-string" if any(isinstance(v, ast.FormattedValue) for v in node.values) else None
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Mod):
            return "%-formatting"
        if isinstance(node.op, ast.Add) and not (
            _is_str_const(node.left) and _is_str_const(node.right)
        ):
            return "string concatenation"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return ".format()"
        if node.func.attr == "join":
            return "str.join()"
    if isinstance(node, ast.Call) and expr_name(node.func).split(".")[-1] == "text" and node.args:
        return dynamic_sql_kind(node.args[0], assignments, depth + 1)
    if isinstance(node, ast.Name) and assignments and node.id in assignments:
        inner = dynamic_sql_kind(assignments[node.id], assignments, depth + 1)
        return f"{inner} (via `{node.id}`)" if inner else None
    return None


def _is_str_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def interpolated_names(
    node: ast.AST | None, assignments: dict[str, ast.AST] | None = None, depth: int = 0
) -> set[str]:
    """Variable names whose values end up inside a dynamically built string."""
    if node is None or depth > 4:
        return set()
    if isinstance(node, ast.Name):
        if assignments and node.id in assignments:
            inner = interpolated_names(assignments[node.id], assignments, depth + 1)
            return inner or {node.id}
        return {node.id}
    names: set[str] = set()
    parts: list[ast.AST] = []
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
    elif isinstance(node, ast.BinOp):
        parts = [node.left, node.right]
    elif isinstance(node, ast.Call):
        parts = [*node.args, *(k.value for k in node.keywords)]
        if isinstance(node.func, ast.Attribute):
            parts.append(node.func.value)
    elif isinstance(node, ast.Tuple | ast.List):
        parts = list(node.elts)
    elif isinstance(node, ast.Attribute | ast.Subscript):
        root = expr_name(node).split(".")[0]
        return {root} if root else set()
    for p in parts:
        if isinstance(p, ast.Constant):
            continue
        names |= interpolated_names(p, assignments, depth + 1)
    return names


def sql_arg(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg in ("sql", "query", "statement", "operation"):
            return kw.value
    return None


def is_sql_sink(call: ast.Call) -> bool:
    return expr_name(call.func).split(".")[-1] in SQL_SINK_NAMES


def is_parameterized(call: ast.Call) -> bool:
    """A constant SQL string with placeholders plus a separate parameters argument."""
    arg = sql_arg(call)
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return False
    has_params = len(call.args) > 1 or any(
        k.arg in ("params", "parameters", "args") for k in call.keywords
    )
    return has_params and bool(PLACEHOLDER_RE.search(arg.value))


def function_assignments(fn: ast.AST) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            out[node.target.id] = node.value
    return out


def enclosing_function(tree: ast.AST, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = node.end_lineno or node.lineno
            if node.lineno <= line <= end and (
                best is None or (end - node.lineno) < ((best.end_lineno or 0) - best.lineno)
            ):
                best = node
    return best


def parse_python(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def calls_in_lines(tree: ast.AST, start: int, end: int) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and start <= n.lineno <= end]


def loop_bodies_with_nested_iteration(fn: ast.AST) -> list[tuple[ast.For, ast.For]]:
    """(outer, inner) pairs of nested for-loops over collections (not ranges)."""
    pairs: list[tuple[ast.For, ast.For]] = []
    for outer in ast.walk(fn):
        if not isinstance(outer, ast.For) or _is_range(outer.iter):
            continue
        for inner in ast.walk(outer):
            if inner is outer or not isinstance(inner, ast.For) or _is_range(inner.iter):
                continue
            outer_names = {n.id for n in ast.walk(outer.target) if isinstance(n, ast.Name)}
            inner_names = {n.id for n in ast.walk(inner.target) if isinstance(n, ast.Name)}
            if _compares(inner, outer_names, inner_names):
                pairs.append((outer, inner))
    return pairs


def _is_range(it: ast.AST) -> bool:
    name = expr_name(it)
    return (
        name in ("range", "enumerate")
        and isinstance(it, ast.Call)
        and (name == "range" or (bool(it.args) and _is_range(it.args[0])))
    )


def _compares(loop: ast.For, a: set[str], b: set[str]) -> bool:
    for node in ast.walk(loop):
        if isinstance(node, ast.Compare):
            used = {expr_name(x).split(".")[0] for x in [node.left, *node.comparators]}
            if used & a and used & b:
                return True
    return False


# --------------------------------------------------------------------------- Python rules


@dataclass
class _Fn:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    assignments: dict[str, ast.AST]
    loop_db_reported: set[int] = field(default_factory=set)


class _PyRules(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.fn_stack: list[_Fn] = []
        self.loops: list[ast.AST] = []
        self._reported_sql: set[int] = set()
        self.coroutines = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
        self.module_assignments: dict[str, ast.AST] = {
            t.id: n.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }

    def add(self, **kw: object) -> None:
        self.findings.append(static_finding(tool=TOOL, file=self.path, **kw))  # type: ignore[arg-type]

    @property
    def assignments(self) -> dict[str, ast.AST]:
        return self.fn_stack[-1].assignments if self.fn_stack else self.module_assignments

    def _visit_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.fn_stack.append(_Fn(node, function_assignments(node)))
        saved = self.loops
        self.loops = []
        self.generic_visit(node)
        for outer, inner in loop_bodies_with_nested_iteration(node):
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
        self.loops = saved
        self.fn_stack.pop()

    visit_FunctionDef = _visit_fn
    visit_AsyncFunctionDef = _visit_fn

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self.loops.append(node)
        self.generic_visit(node)
        self.loops.pop()

    visit_For = _visit_loop
    visit_AsyncFor = _visit_loop
    visit_While = _visit_loop

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        broad = node.type is None or expr_name(node.type) in ("Exception", "BaseException")
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
        call = node.value
        if isinstance(call, ast.Call):
            name = expr_name(call.func)
            short = name.split(".")[-1]
            local = name if "." not in name else (name[5:] if name.startswith("self.") else "")
            if local and local in self.coroutines and short not in SCHEDULERS:
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
                    suggested_fix=f"Use `await {name}(...)` (or schedule it with "
                    "asyncio.create_task).",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = expr_name(node.func)
        short = name.split(".")[-1]
        self._sql(node, short)
        self._injection(node, name)
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
        if name == "yaml.load" and not any(
            k.arg == "Loader" and "Safe" in expr_name(k.value) for k in node.keywords
        ):
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
        if any(
            k.arg == "verify" and isinstance(k.value, ast.Constant) and k.value.value is False
            for k in node.keywords
        ):
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
        if (
            short in ("md5", "sha1")
            and name.startswith("hashlib")
            and self.fn_stack
            and (SENSITIVE_FN.search(self.fn_stack[-1].node.name))
        ):
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
        self._blocking(node, name)
        self._loop_db(node, name, short)
        self.generic_visit(node)

    def _sql(self, node: ast.Call, short: str) -> None:
        if short not in SQL_SINK_NAMES or id(node) in self._reported_sql:
            return
        arg = sql_arg(node)
        if isinstance(arg, ast.Call):  # execute(text(...)): report once, at the outer call
            self._reported_sql.add(id(arg))
        kind = dynamic_sql_kind(arg, self.assignments)
        if not kind:
            return
        names = sorted(interpolated_names(sql_arg(node), self.assignments))
        via = f" (values: {', '.join(f'`{n}`' for n in names)})" if names else ""
        self.add(
            rule="sql-injection",
            category=Category.SECURITY,
            severity=Severity.HIGH,
            confidence=0.85 if "via" not in kind else 0.75,
            line=node.lineno,
            end_line=node.end_lineno,
            title="SQL query built with string interpolation",
            explanation=(
                f"The SQL passed to `{short}()` is built with {kind}{via}. If any of those "
                "values come from a user, they can change the query (SQL injection)."
            ),
            tags=["sql-injection"],
            suggested_fix="Use a parameterized query: pass values as the second argument "
            "(e.g. `execute('... WHERE name = ?', (name,))`).",
        )

    def _injection(self, node: ast.Call, name: str) -> None:
        first = node.args[0] if node.args else None
        dynamic = first is not None and not isinstance(first, ast.Constant)
        if name in ("eval", "exec") and dynamic:
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
        shell = any(
            k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value
            for k in node.keywords
        )
        if dynamic and (
            name in ("os.system", "os.popen") or (name.startswith("subprocess.") and shell)
        ):
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

    def _blocking(self, node: ast.Call, name: str) -> None:
        if not self.fn_stack or not isinstance(self.fn_stack[-1].node, ast.AsyncFunctionDef):
            return
        label = BLOCKING_CALLS.get(name)
        if label is None:
            return
        self.add(
            rule="blocking-in-async",
            category=Category.PERFORMANCE,
            severity=Severity.MEDIUM,
            confidence=0.85,
            line=node.lineno,
            title=f"Blocking call {label} inside async function",
            explanation=(
                f"`{self.fn_stack[-1].node.name}` is `async`, but {label} blocks the event "
                "loop: every other request on this worker stalls until it returns."
            ),
            tags=["blocking-in-async", "async"],
            suggested_fix="Use the async equivalent (asyncio.sleep, httpx.AsyncClient, an async "
            "DB driver) or run it in a thread with asyncio.to_thread.",
        )

    def _loop_db(self, node: ast.Call, name: str, short: str) -> None:
        if not self.loops or not self.fn_stack or short not in DB_EXEC_METHODS:
            return
        loop = self.loops[-1]
        fn = self.fn_stack[-1]
        if id(loop) in fn.loop_db_reported:
            return
        fn.loop_db_reported.add(id(loop))
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


# --------------------------------------------------------------------------- JS/TS rules

JS_RULES: list[tuple[str, re.Pattern[str], Category, Severity, float, str, list[str], str]] = [
    (
        "sql-injection",
        re.compile(
            r"\.(query|execute|raw|\$queryRawUnsafe|\$executeRawUnsafe)\s*\(\s*(`[^`]*\$\{|['\"][^'\"]*['\"]\s*\+)"
        ),
        Category.SECURITY,
        Severity.HIGH,
        0.85,
        "SQL query built with string interpolation",
        ["sql-injection"],
        "Use placeholders ($1 / ?) and pass values as a separate array.",
    ),
    (
        "code-injection",
        re.compile(r"(?<![\w.])(eval|new\s+Function)\s*\((?!\s*['\"`][^'\"`]*['\"`]\s*\))"),
        Category.SECURITY,
        Severity.HIGH,
        0.8,
        "Dynamic code execution",
        ["code-injection"],
        "Avoid eval/new Function; parse the data explicitly.",
    ),
    (
        "command-injection",
        re.compile(r"\b(exec|execSync)\s*\(\s*(`[^`]*\$\{|['\"][^'\"]*['\"]\s*\+)"),
        Category.SECURITY,
        Severity.HIGH,
        0.8,
        "Shell command built from a variable",
        ["command-injection"],
        "Use execFile/spawn with an argument array.",
    ),
    (
        "xss",
        re.compile(r"(\.innerHTML\s*=(?!\s*['\"`][^'\"`$]*['\"`]\s*;?$)|dangerouslySetInnerHTML)"),
        Category.SECURITY,
        Severity.MEDIUM,
        0.6,
        "HTML injected without escaping",
        ["xss"],
        "Use textContent or sanitize the HTML (e.g. DOMPurify).",
    ),
    (
        "tls-verify-disabled",
        re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"),
        Category.SECURITY,
        Severity.MEDIUM,
        0.85,
        "TLS certificate verification disabled",
        ["tls"],
        "Keep certificate verification on; configure a CA instead.",
    ),
]


def js_rule_findings(path: str, source: str) -> list[Finding]:
    out: list[Finding] = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        for rule, pattern, cat, sev, conf, title, tags, fix in JS_RULES:
            if pattern.search(line):
                out.append(
                    static_finding(
                        tool=TOOL,
                        rule=rule,
                        category=cat,
                        severity=sev,
                        confidence=conf,
                        title=title,
                        file=path,
                        line=i,
                        tags=tags,
                        suggested_fix=fix,
                        explanation=f"{title} at line {i}.",
                    )
                )
    return out


def symbols_db_in_loop(fs: FileSymbols) -> list[Finding]:
    """Language-neutral N+1 detection from extracted symbols (used for JS/TS)."""
    out: list[Finding] = []
    seen: set[str] = set()
    for op in fs.db_operations:
        if not op.in_loop or op.function in seen:
            continue
        seen.add(op.function)
        out.append(
            static_finding(
                tool=TOOL,
                rule="n-plus-one",
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM,
                confidence=0.7,
                line=op.line,
                file=fs.path,
                title="Database query inside a loop (N+1 queries)",
                explanation=(
                    f"`{op.detail}` in `{op.function}` runs once per loop iteration, issuing "
                    "one round trip per element."
                ),
                tags=["n+1"],
                suggested_fix="Batch the lookups into one query before the loop.",
            )
        )
    return out


class BuiltinAnalyzer:
    name = "sentinel"
    languages = frozenset({Language.PYTHON, Language.TYPESCRIPT, Language.JAVASCRIPT})

    def __init__(self, registry: LanguageRegistry | None = None) -> None:
        self.registry = registry

    def is_available(self) -> bool:
        return True

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        start = time.monotonic()
        findings: list[Finding] = []
        js_sources: dict[str, str] = {}
        for rel in files:
            try:
                source = (workspace / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            findings.extend(self.analyze_source(rel, source))
            if not rel.endswith((".py", ".pyi")):
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
        if path.endswith((".py", ".pyi")):
            tree = parse_python(source)
            if tree is None:
                return []
            rules = _PyRules(path, tree)
            rules.visit(tree)
            return rules.findings
        return js_rule_findings(path, source)
