"""AST helpers that recognise risky Python patterns.

Shared by two callers that must agree with each other:

- ``python_rules.py`` (Sentinel's own static rules) uses them to *report* problems;
- ``probes/`` (verification probes) uses them to *confirm or refute* an AI claim,
  e.g. "is the SQL on line 34 really built from a string?".
"""

from __future__ import annotations

import ast
import re

from sentinel.analysis.ast.python_analyzer import expr_name
from sentinel.analysis.ast.python_sql import DB_EXEC_METHODS

SQL_SINK_NAMES = DB_EXEC_METHODS | {"text"}
SQL_KEYWORD_ARGS = ("sql", "query", "statement", "operation")
PARAMS_KEYWORD_ARGS = ("params", "parameters", "args")
PLACEHOLDER_RE = re.compile(r"(%s|\?|:\w+|\$\d+|%\(\w+\)s)")
STRING_BUILDER_METHODS = {"format": ".format()", "join": "str.join()"}
# How many variable assignments / wrapper calls to follow back from a SQL argument.
MAX_FOLLOW_DEPTH = 4
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

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


# --------------------------------------------------------------------------- SQL


def dynamic_sql_kind(
    node: ast.AST | None, assignments: dict[str, ast.AST] | None = None, depth: int = 0
) -> str | None:
    """How a SQL argument is built dynamically (``"f-string"`` ...), or None if constant.

    Follows ``text(...)`` wrappers and local variables (``query = f"..."``).
    """
    if node is None or depth > MAX_FOLLOW_DEPTH:
        return None
    if isinstance(node, ast.JoinedStr):
        return "f-string" if any(isinstance(v, ast.FormattedValue) for v in node.values) else None
    if isinstance(node, ast.BinOp):
        return _operator_kind(node)
    if isinstance(node, ast.Call):
        return _call_kind(node, assignments, depth)
    if isinstance(node, ast.Name) and assignments and node.id in assignments:
        inner = dynamic_sql_kind(assignments[node.id], assignments, depth + 1)
        return f"{inner} (via `{node.id}`)" if inner else None
    return None


def interpolated_names(
    node: ast.AST | None, assignments: dict[str, ast.AST] | None = None, depth: int = 0
) -> set[str]:
    """Variable names whose values end up inside a dynamically built string."""
    if node is None or depth > MAX_FOLLOW_DEPTH:
        return set()
    if isinstance(node, ast.Name):
        if assignments and node.id in assignments:
            return interpolated_names(assignments[node.id], assignments, depth + 1) or {node.id}
        return {node.id}
    if isinstance(node, ast.Attribute | ast.Subscript):
        root = expr_name(node).split(".")[0]
        return {root} if root else set()
    names: set[str] = set()
    for part in _string_parts(node):
        if not isinstance(part, ast.Constant):
            names |= interpolated_names(part, assignments, depth + 1)
    return names


def sql_arg(call: ast.Call) -> ast.AST | None:
    """The SQL argument of an ``execute``-style call (first positional or ``sql=``)."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in SQL_KEYWORD_ARGS:
            return keyword.value
    return None


def is_sql_sink(call: ast.Call) -> bool:
    """True for calls that execute SQL (``execute``, ``executemany``, ``text`` ...)."""
    return expr_name(call.func).split(".")[-1] in SQL_SINK_NAMES


def is_parameterized(call: ast.Call) -> bool:
    """A constant SQL string with placeholders plus a separate parameters argument."""
    arg = sql_arg(call)
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return False
    has_params = len(call.args) > 1 or any(k.arg in PARAMS_KEYWORD_ARGS for k in call.keywords)
    return has_params and bool(PLACEHOLDER_RE.search(arg.value))


def _operator_kind(node: ast.BinOp) -> str | None:
    if isinstance(node.op, ast.Mod):
        return "%-formatting"
    if isinstance(node.op, ast.Add) and not (
        _is_str_const(node.left) and _is_str_const(node.right)
    ):
        return "string concatenation"
    return None


def _call_kind(node: ast.Call, assignments: dict[str, ast.AST] | None, depth: int) -> str | None:
    """``"...".format(x)`` / ``", ".join(xs)``, or a ``text(...)`` wrapper to look inside."""
    if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_BUILDER_METHODS:
        return STRING_BUILDER_METHODS[node.func.attr]
    if expr_name(node.func).split(".")[-1] == "text" and node.args:
        return dynamic_sql_kind(node.args[0], assignments, depth + 1)
    return None


def _string_parts(node: ast.AST) -> list[ast.AST]:
    """Sub-expressions whose values flow into a string built from ``node``."""
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
    if isinstance(node, ast.BinOp):
        return [node.left, node.right]
    if isinstance(node, ast.Call):
        parts: list[ast.AST] = [*node.args, *(k.value for k in node.keywords)]
        if isinstance(node.func, ast.Attribute):
            parts.append(node.func.value)
        return parts
    if isinstance(node, ast.Tuple | ast.List):
        return list(node.elts)
    return []


def _is_str_const(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


# --------------------------------------------------------------------------- functions


def parse_python(source: str) -> ast.Module | None:
    """Parse Python source, or None when it does not parse."""
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def function_assignments(fn: ast.AST) -> dict[str, ast.AST]:
    """``name -> assigned expression`` for every simple assignment inside ``fn``."""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            out[node.target.id] = node.value
    return out


def enclosing_function(tree: ast.AST, line: int) -> FunctionNode | None:
    """The innermost function whose body contains ``line``."""
    best: FunctionNode | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = node.end_lineno or node.lineno
        is_inside = node.lineno <= line <= end
        if is_inside and (best is None or end - node.lineno < (best.end_lineno or 0) - best.lineno):
            best = node
    return best


def calls_in_lines(tree: ast.AST, start: int, end: int) -> list[ast.Call]:
    """Every call expression that starts between ``start`` and ``end``."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and start <= n.lineno <= end]


# --------------------------------------------------------------------------- loops


def loop_bodies_with_nested_iteration(fn: ast.AST) -> list[tuple[ast.For, ast.For]]:
    """``(outer, inner)`` pairs of nested for-loops over collections that compare elements.

    Loops over ``range(...)`` are ignored: they are usually index arithmetic, not a
    pairwise comparison of two collections.
    """
    pairs: list[tuple[ast.For, ast.For]] = []
    for outer in ast.walk(fn):
        if not isinstance(outer, ast.For) or _is_range(outer.iter):
            continue
        for inner in ast.walk(outer):
            if inner is outer or not isinstance(inner, ast.For) or _is_range(inner.iter):
                continue
            if _compares(inner, _target_names(outer), _target_names(inner)):
                pairs.append((outer, inner))
    return pairs


def _target_names(loop: ast.For) -> set[str]:
    return {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}


def _is_range(iterable: ast.AST) -> bool:
    """``range(...)`` or ``enumerate(range(...))``."""
    name = expr_name(iterable)
    if not isinstance(iterable, ast.Call) or name not in ("range", "enumerate"):
        return False
    return name == "range" or (bool(iterable.args) and _is_range(iterable.args[0]))


def _compares(loop: ast.For, outer_names: set[str], inner_names: set[str]) -> bool:
    """True when the loop compares a variable of each loop with the other."""
    for node in ast.walk(loop):
        if isinstance(node, ast.Compare):
            used = {expr_name(x).split(".")[0] for x in [node.left, *node.comparators]}
            if used & outer_names and used & inner_names:
                return True
    return False
