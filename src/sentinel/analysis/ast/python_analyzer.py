"""Python language adapter built on the standard-library ``ast`` module.

Extracts symbols, imports, call sites (with loop/await context), HTTP endpoints and
database operations. It is deliberately approximate — it does no type inference — but
it is exact about structure, which is what the code graph needs.
"""

from __future__ import annotations

import ast
import posixpath

from sentinel.analysis.ast.python_sql import db_operation_kind, sql_tables
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
ROUTE_DECORATORS = frozenset({"route", "api_route"})
ROUTE_KEYWORDS = ("path", "rule")
DEFAULT_ROUTE_METHOD = "GET"
MODULE_SYMBOL = "<module>"
MAIN_BLOCK = "__main__"


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
        return self.scope[-1][0] if self.scope else MODULE_SYMBOL

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
        """Record the class, then visit its body inside the class scope."""
        qualified = self._qualify(node.name)
        self.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qualified,
                kind=SymbolKind.CLASS,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                parent=self.class_scope,
                decorators=[expr_name(d) for d in node.decorator_list],
                bases=[expr_name(b) for b in node.bases if expr_name(b)],
            )
        )
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_body(qualified, SymbolKind.CLASS, node.body)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Record the function (and any route it declares), then visit its body."""
        qualified = self._qualify(node.name)
        in_class = bool(self.scope) and self.scope[-1][1] is SymbolKind.CLASS
        kind = SymbolKind.METHOD if in_class else SymbolKind.FUNCTION
        if self.is_test_file and node.name.startswith("test"):
            kind = SymbolKind.TEST
        self.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qualified,
                kind=kind,
                line_start=min([node.lineno, *(d.lineno for d in node.decorator_list)]),
                line_end=node.end_lineno or node.lineno,
                parent=self.class_scope,
                decorators=[expr_name(d) for d in node.decorator_list],
                params=_parameter_names(node.args),
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )
        )
        for decorator in node.decorator_list:
            self.endpoints += endpoints_from_decorator(decorator, qualified)
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        self._visit_body(qualified, kind, node.body)

    def _visit_body(self, qualified: str, kind: SymbolKind, body: list[ast.stmt]) -> None:
        """Visit a class or function body in its own scope (loops do not leak inward)."""
        self.scope.append((qualified, kind))
        outer_loop_depth, self.loop_depth = self.loop_depth, 0
        for statement in body:
            self.visit(statement)
        self.loop_depth = outer_loop_depth
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
            self.scope.append((MAIN_BLOCK, SymbolKind.FUNCTION))
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
        """Record a ``DbOperation`` when the call reads or writes a database."""
        operation, sql = db_operation_kind(callee, node)
        if operation is None:
            return
        tables = sql_tables(sql)
        detail = callee + (f" [{', '.join(tables)}]" if tables else "")
        self.db_ops.append(
            DbOperation(
                function=self.current,
                operation=operation,
                line=node.lineno,
                detail=detail,
                in_loop=self.loop_depth > 0,
            )
        )


class PythonAnalyzer:
    """``LanguageAnalyzer`` for Python files."""

    language = Language.PYTHON
    extensions: tuple[str, ...] = (".py", ".pyi")

    def analyze(self, path: str, source: str) -> FileSymbols:
        """Parse one file; a syntax error is reported in ``parse_error``, not raised."""
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
        module = Symbol(
            name=result.module_name.split(".")[-1] or path,
            qualified_name=MODULE_SYMBOL,
            kind=SymbolKind.MODULE,
            line_start=1,
            line_end=max(result.loc, 1),
        )
        result.symbols = [module, *visitor.symbols]
        if visitor.main_span is not None:
            result.symbols.append(_main_block_symbol(*visitor.main_span))
        result.imports = visitor.imports
        result.calls = visitor.calls
        result.endpoints = visitor.endpoints
        result.db_operations = visitor.db_ops
        return result


def endpoints_from_decorator(decorator: ast.expr, handler: str) -> list[EndpointRef]:
    """Routes declared by ``@app.get("/x")``, ``@app.post(path="/x")`` or ``@app.route``."""
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return []
    route = _route_argument(decorator)
    attribute = decorator.func.attr.lower()
    if route is None:
        return []
    if attribute in HTTP_METHODS:
        methods = [attribute.upper()]
    elif attribute in ROUTE_DECORATORS:
        methods = _declared_methods(decorator)
    else:
        return []
    return [
        EndpointRef(method=method, route=route, handler=handler, line=decorator.lineno)
        for method in methods
    ]


def _route_argument(decorator: ast.Call) -> str | None:
    """The route path: the first string argument, or a ``path=`` / ``rule=`` keyword."""
    route = None
    first = decorator.args[0] if decorator.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        route = first.value
    for keyword in decorator.keywords:
        if keyword.arg in ROUTE_KEYWORDS and isinstance(keyword.value, ast.Constant):
            route = str(keyword.value.value)
    return route


def _declared_methods(decorator: ast.Call) -> list[str]:
    """HTTP methods from ``methods=[...]`` (Flask style); GET when not given."""
    for keyword in decorator.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, ast.List | ast.Tuple | ast.Set):
            declared = [
                str(e.value).upper() for e in keyword.value.elts if isinstance(e, ast.Constant)
            ]
            if declared:
                return declared
    return [DEFAULT_ROUTE_METHOD]


def _parameter_names(args: ast.arguments) -> list[str]:
    """Parameter names, with ``*args`` / ``**kwargs`` marked."""
    params = [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
    if args.vararg:
        params.append("*" + args.vararg.arg)
    if args.kwarg:
        params.append("**" + args.kwarg.arg)
    return params


def _main_block_symbol(start: int, end: int) -> Symbol:
    """A pseudo-function for ``if __name__ == "__main__":`` so it can be an entry point."""
    return Symbol(
        name=MAIN_BLOCK,
        qualified_name=MAIN_BLOCK,
        kind=SymbolKind.FUNCTION,
        line_start=start,
        line_end=end,
        decorators=["entrypoint"],
    )
