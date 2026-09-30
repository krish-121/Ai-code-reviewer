"""Python language adapter built on the standard-library ``ast`` module.

Extracts symbols, imports, call sites (with loop/await context), HTTP endpoints and
database operations. It is deliberately approximate — it does no type inference — but
it is exact about structure, which is what the code graph needs.
"""

from __future__ import annotations

import ast
import posixpath
import re

from sentinel.core.domain.code import (
    CallSite,
    DbOperation,
    EndpointRef,
    FileSymbols,
    ImportRef,
    Symbol,
    SymbolKind,
)
from sentinel.core.domain.models import Language

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "websocket"}
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
ENTRYPOINT_DECORATORS = ("command", "group", "task", "route", "handler", "callback", "cli")


def module_name_for(path: str) -> str:
    stem = path[:-3] if path.endswith(".py") else path
    parts = [p for p in stem.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]
    return ".".join(parts)


def is_python_test_file(path: str) -> bool:
    base = posixpath.basename(path)
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base == "conftest.py"
        or "/tests/" in f"/{path}"
        or "/test/" in f"/{path}"
    )


def expr_name(node: ast.AST) -> str:
    """Best-effort dotted name for an expression: ``self.repo.find``, ``requests.get``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return expr_name(node.func)
    if isinstance(node, ast.Subscript):
        return expr_name(node.value)
    return ""


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
    if not sql:
        return "unknown"
    m = SQL_VERB_RE.match(sql)
    if not m:
        return "unknown"
    return "read" if m.group(1).lower() in ("select", "with") else "write"


def sql_tables(sql: str | None) -> list[str]:
    if not sql:
        return []
    return list(dict.fromkeys(t.split(".")[-1].lower() for t in SQL_TABLE_RE.findall(sql)))


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str, is_test_file: bool) -> None:
        self.path = path
        self.is_test_file = is_test_file
        self.symbols: list[Symbol] = []
        self.imports: list[ImportRef] = []
        self.calls: list[CallSite] = []
        self.endpoints: list[EndpointRef] = []
        self.db_ops: list[DbOperation] = []
        self.scope: list[tuple[str, SymbolKind]] = []  # (qualified name, kind)
        self.loop_depth = 0
        self.main_span: tuple[int, int] | None = None
        self._awaited: set[int] = set()

    # ---------------------------------------------------------------- helpers
    @property
    def current(self) -> str:
        return self.scope[-1][0] if self.scope else "<module>"

    @property
    def class_scope(self) -> str | None:
        for name, kind in reversed(self.scope):
            if kind is SymbolKind.CLASS:
                return name
        return None

    def _qualify(self, name: str) -> str:
        return f"{self.current}.{name}" if self.scope else name

    # ---------------------------------------------------------------- imports
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports.append(
                ImportRef(
                    module=alias.name,
                    aliases={local: alias.name if alias.asname else alias.name.split(".")[0]},
                    line=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [a.name for a in node.names]
        aliases = {(a.asname or a.name): a.name for a in node.names}
        self.imports.append(
            ImportRef(
                module=node.module or "",
                names=names,
                aliases=aliases,
                line=node.lineno,
                level=node.level or 0,
            )
        )

    # ---------------------------------------------------------------- definitions
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qn = self._qualify(node.name)
        self.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qn,
                kind=SymbolKind.CLASS,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                parent=self.class_scope,
                decorators=[expr_name(d) for d in node.decorator_list],
                bases=[expr_name(b) for b in node.bases if expr_name(b)],
            )
        )
        for d in node.decorator_list:
            self.visit(d)
        self.scope.append((qn, SymbolKind.CLASS))
        saved_loop = self.loop_depth
        self.loop_depth = 0
        for stmt in node.body:
            self.visit(stmt)
        self.loop_depth = saved_loop
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qn = self._qualify(node.name)
        in_class = bool(self.scope) and self.scope[-1][1] is SymbolKind.CLASS
        kind = SymbolKind.METHOD if in_class else SymbolKind.FUNCTION
        if self.is_test_file and node.name.startswith("test"):
            kind = SymbolKind.TEST
        decorators = [expr_name(d) for d in node.decorator_list]
        args = node.args
        params = [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
        if args.vararg:
            params.append("*" + args.vararg.arg)
        if args.kwarg:
            params.append("**" + args.kwarg.arg)
        self.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qn,
                kind=kind,
                line_start=min([node.lineno, *(d.lineno for d in node.decorator_list)]),
                line_end=node.end_lineno or node.lineno,
                parent=self.class_scope,
                decorators=decorators,
                params=params,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )
        )
        for d in node.decorator_list:
            self._maybe_endpoint(d, qn)
            self.visit(d)
        for default in [*args.defaults, *args.kw_defaults]:
            if default is not None:
                self.visit(default)
        self.scope.append((qn, kind))
        saved_loop = self.loop_depth
        self.loop_depth = 0
        for stmt in node.body:
            self.visit(stmt)
        self.loop_depth = saved_loop
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.scope:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.symbols.append(
                        Symbol(
                            name=target.id,
                            qualified_name=target.id,
                            kind=SymbolKind.VARIABLE,
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                        )
                    )
        self.generic_visit(node)

    def _maybe_endpoint(self, deco: ast.expr, handler: str) -> None:
        if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
            return
        attr = deco.func.attr.lower()
        route = None
        if (
            deco.args
            and isinstance(deco.args[0], ast.Constant)
            and isinstance(deco.args[0].value, str)
        ):
            route = deco.args[0].value
        for kw in deco.keywords:
            if kw.arg in ("path", "rule") and isinstance(kw.value, ast.Constant):
                route = str(kw.value.value)
        if route is None:
            return
        if attr in HTTP_METHODS:
            self.endpoints.append(
                EndpointRef(method=attr.upper(), route=route, handler=handler, line=deco.lineno)
            )
        elif attr in ("route", "api_route"):
            methods = ["GET"]
            for kw in deco.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List | ast.Tuple | ast.Set):
                    methods = [
                        str(e.value).upper() for e in kw.value.elts if isinstance(e, ast.Constant)
                    ] or methods
            for m in methods:
                self.endpoints.append(
                    EndpointRef(method=m, route=route, handler=handler, line=deco.lineno)
                )

    # ---------------------------------------------------------------- control flow
    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        if isinstance(node, ast.For | ast.AsyncFor):
            self.visit(node.iter)
            self.visit(node.target)
        else:
            self.visit(node.test)
        self.loop_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self.loop_depth -= 1
        for stmt in node.orelse:
            self.visit(stmt)

    visit_For = _visit_loop
    visit_AsyncFor = _visit_loop
    visit_While = _visit_loop

    def _visit_comp(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) -> None:
        for gen in node.generators:
            self.visit(gen.iter)
        self.loop_depth += 1
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        for gen in node.generators:
            for cond in gen.ifs:
                self.visit(cond)
        self.loop_depth -= 1

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_GeneratorExp = _visit_comp
    visit_DictComp = _visit_comp

    def visit_If(self, node: ast.If) -> None:
        is_main = (
            not self.scope
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and any(
                isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators
            )
        )
        if is_main:
            self.main_span = (node.lineno, node.end_lineno or node.lineno)
            self.scope.append(("__main__", SymbolKind.FUNCTION))
            self.generic_visit(node)
            self.scope.pop()
            return
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        if isinstance(node.value, ast.Call):
            self._awaited.add(id(node.value))
        self.generic_visit(node)

    # ---------------------------------------------------------------- calls
    def visit_Call(self, node: ast.Call) -> None:
        callee = expr_name(node.func)
        if callee:
            self.calls.append(
                CallSite(
                    caller=self.current,
                    callee=callee,
                    line=node.lineno,
                    in_loop=self.loop_depth > 0,
                    awaited=id(node) in self._awaited,
                )
            )
            self._maybe_db(node, callee)
        self.generic_visit(node)

    def _maybe_db(self, node: ast.Call, callee: str) -> None:
        parts = callee.split(".")
        method = parts[-1]
        receiver = ".".join(parts[:-1]).lower()
        op: str | None = None
        sql = None
        if method in DB_EXEC_METHODS:
            sql = sql_literal(node.args[0]) if node.args else None
            op = classify_sql(sql)
        elif (
            receiver
            and not any(m in receiver.split(".") for m in DB_EXEC_METHODS)
            and any(h in receiver for h in DB_RECEIVER_HINTS)
        ):
            if method in ORM_READ_METHODS:
                op = "read"
            elif method in ORM_WRITE_METHODS:
                op = "write"
        if op is None:
            return
        tables = sql_tables(sql)
        detail = callee + (f" [{', '.join(tables)}]" if tables else "")
        self.db_ops.append(
            DbOperation(
                function=self.current,
                operation=op,
                line=node.lineno,
                detail=detail,
                in_loop=self.loop_depth > 0,
            )
        )


class PythonAnalyzer:
    language = Language.PYTHON
    extensions: tuple[str, ...] = (".py", ".pyi")

    def analyze(self, path: str, source: str) -> FileSymbols:
        is_test = is_python_test_file(path)
        result = FileSymbols(
            path=path,
            language=Language.PYTHON,
            module_name=module_name_for(path),
            is_test_file=is_test,
            loc=source.count("\n") + (0 if source.endswith("\n") or not source else 1),
        )
        try:
            tree = ast.parse(source, filename=path, type_comments=False)
        except SyntaxError as exc:
            result.parse_error = f"SyntaxError: {exc.msg} (line {exc.lineno})"
            return result
        except ValueError as exc:  # e.g. source contains NUL bytes
            result.parse_error = f"ValueError: {exc}"
            return result
        visitor = _Visitor(path, is_test)
        visitor.visit(tree)
        # The module itself, so module-level code has a node to attach calls to.
        result.symbols = [
            Symbol(
                name=result.module_name.split(".")[-1] or path,
                qualified_name="<module>",
                kind=SymbolKind.MODULE,
                line_start=1,
                line_end=max(result.loc, 1),
            ),
            *visitor.symbols,
        ]
        if visitor.main_span is not None:
            result.symbols.append(
                Symbol(
                    name="__main__",
                    qualified_name="__main__",
                    kind=SymbolKind.FUNCTION,
                    line_start=visitor.main_span[0],
                    line_end=visitor.main_span[1],
                    decorators=["entrypoint"],
                )
            )
        result.imports = visitor.imports
        result.calls = visitor.calls
        result.endpoints = visitor.endpoints
        result.db_operations = visitor.db_ops
        return result
