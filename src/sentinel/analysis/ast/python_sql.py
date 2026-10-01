"""Recognising database access in Python code: SQL text, query kind, tables, ORM calls.

Used by ``python_analyzer.py`` to record ``DbOperation``s (which become READS/WRITES edges
in the code graph and power N+1 detection), and by the static rules for the list of
methods that execute SQL.
"""

from __future__ import annotations

import ast
import re

DB_EXEC_METHODS = {"execute", "executemany", "executescript", "raw", "mogrify"}
ORM_READ_METHODS = {
    "query",
    "filter",
    "filter_by",
    "get",
    "select_related",
    "prefetch_related",
    "exclude",
    "find",
    "find_one",
    "aggregate",
    "scalars",
}
ORM_WRITE_METHODS = {
    "add",
    "add_all",
    "commit",
    "delete",
    "merge",
    "flush",
    "bulk_create",
    "update",
    "create",
    "save",
    "insert_one",
    "insert_many",
    "update_one",
    "delete_one",
    "bulk_update",
}
DB_RECEIVER_HINTS = (
    "cursor",
    "cur",
    "conn",
    "connection",
    "db",
    "session",
    "objects",
    "engine",
    "collection",
    "repo",
    "database",
    "tx",
    "transaction",
)
SQL_VERB_RE = re.compile(
    r"^\s*(select|with|insert|update|delete|replace|merge|create|drop|alter)\b", re.I
)
SQL_TABLE_RE = re.compile(r"\b(?:from|into|update|join)\s+[`\"\[]?([A-Za-z_][\w.]*)", re.I)


def sql_literal(node: ast.AST | None) -> str | None:
    """The static text of a SQL argument (literal parts of f-strings included)."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    if isinstance(node, ast.BinOp):
        left = sql_literal(node.left)
        right = sql_literal(node.right)
        return (left or "") + (right or "") or None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return sql_literal(node.func.value)
        if node.func.attr in ("text",) and node.args:
            return sql_literal(node.args[0])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "text":
        return sql_literal(node.args[0]) if node.args else None
    return None


def classify_sql(sql: str | None) -> str:
    """``"read"`` for SELECT/WITH, ``"write"`` for other statements, else ``"unknown"``."""
    if not sql:
        return "unknown"
    m = SQL_VERB_RE.match(sql)
    if not m:
        return "unknown"
    return "read" if m.group(1).lower() in ("select", "with") else "write"


def sql_tables(sql: str | None) -> list[str]:
    """Table names after FROM / INTO / UPDATE / JOIN, lower-cased, in order of appearance."""
    if not sql:
        return []
    return list(dict.fromkeys(t.split(".")[-1].lower() for t in SQL_TABLE_RE.findall(sql)))


def db_operation_kind(callee: str, node: ast.Call) -> tuple[str | None, str | None]:
    """``(operation, sql)`` for a call that touches a database, else ``(None, None)``.

    ``operation`` is ``"read"``, ``"write"`` or ``"unknown"``. Raw SQL calls
    (``cursor.execute("SELECT ...")``) are classified from the SQL text; ORM calls
    (``session.query``, ``User.objects.filter``) from the method name, but only when the
    receiver looks like a database handle.
    """
    parts = callee.split(".")
    method = parts[-1]
    receiver = ".".join(parts[:-1]).lower()
    if method in DB_EXEC_METHODS:
        sql = sql_literal(node.args[0]) if node.args else None
        return classify_sql(sql), sql
    looks_like_db = any(hint in receiver for hint in DB_RECEIVER_HINTS)
    chained_on_execute = any(m in receiver.split(".") for m in DB_EXEC_METHODS)
    if not receiver or chained_on_execute or not looks_like_db:
        return None, None
    if method in ORM_READ_METHODS:
        return "read", None
    if method in ORM_WRITE_METHODS:
        return "write", None
    return None, None
