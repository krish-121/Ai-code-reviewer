"""Build a ``CodeGraph`` from per-file ``FileSymbols``.

Called by the orchestrator's build-graph stage, after the language analyzers ran.
Building happens in passes, because an edge can only be drawn once both ends exist:

1. index module names, so imports can be resolved;
2. add a node for every file and symbol;
3. resolve imports (IMPORTS edges);
4. add inheritance (INHERITS / IMPLEMENTS edges);
5. add endpoints (ROUTES), calls (CALLS, TESTS) and database access (READS / WRITES).

Name resolution lives in ``resolution.py``. It is intentionally conservative: a call edge
is only added when the target can be identified with reasonable certainty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sentinel.analysis.graph.resolution import (
    JS_SOURCE_SUFFIX_RE,
    MODULE_KEY,
    CallResolver,
    SymbolTable,
    resolve_imports,
)
from sentinel.analysis.graph.variables import add_variable_edges
from sentinel.core.domain.code import DbOperation, FileSymbols, Symbol, SymbolKind
from sentinel.core.domain.graph import CODE_KINDS, CodeGraph, EdgeKind, GraphNode, NodeKind, node_id
from sentinel.core.domain.models import Language

KIND_MAP = {
    SymbolKind.MODULE: NodeKind.MODULE,
    SymbolKind.VARIABLE: NodeKind.VARIABLE,
    SymbolKind.CLASS: NodeKind.CLASS,
    SymbolKind.FUNCTION: NodeKind.FUNCTION,
    SymbolKind.METHOD: NodeKind.METHOD,
    SymbolKind.TEST: NodeKind.TEST,
}
# A decorator whose last name part is one of these marks an entry point (@app.get, @click.command)
ENTRY_DECORATOR_HINTS = frozenset(
    "route command group task get post put delete patch websocket handler listener "
    "entrypoint".split()
)
ENTRY_NAMES = frozenset({"main"})
FILE_NODE_NAME = "<file>"
GENERIC_DATABASE = "database"
TABLE_LIST_RE = re.compile(r"\[([^\]]+)\]")  # DbOperation.detail lists tables as "[a, b]"
TRUE = "true"  # graph node meta values are strings


@dataclass
class GraphBuildResult:
    """The graph plus resolution statistics (shown on the build-graph stage)."""

    graph: CodeGraph
    files: dict[str, FileSymbols]
    unresolved_calls: int = 0
    resolved_calls: int = 0


def build_graph(files: dict[str, FileSymbols]) -> GraphBuildResult:
    """Build the code graph for a set of analyzed files."""
    return GraphBuilder(files).build()


class GraphBuilder:
    """Runs the build passes described in the module docstring."""

    def __init__(self, files: dict[str, FileSymbols]) -> None:
        self.files = files
        self.graph = CodeGraph()
        self.table = SymbolTable(graph=self.graph, files=files)
        self.resolver = CallResolver(self.table)
        self.resolved = 0
        self.unresolved = 0

    def build(self) -> GraphBuildResult:
        """Run every pass and return the finished graph."""
        self._index_modules()
        for fs in self.files.values():
            self._add_file(fs)
        for fs in self.files.values():
            self._add_imports(fs)
        add_variable_edges(self.table, self.files)
        for fs in self.files.values():
            self._add_inheritance(fs)
        for fs in self.files.values():
            self._add_endpoints(fs)
            self._add_calls(fs)
            self._add_db_operations(fs)
        return GraphBuildResult(
            graph=self.graph,
            files=self.files,
            unresolved_calls=self.unresolved,
            resolved_calls=self.resolved,
        )

    # ------------------------------------------------------------------ pass 1-2: nodes
    def _index_modules(self) -> None:
        """Map module names (``app.db``, ``src/db``) to file paths for import resolution."""
        for path, fs in self.files.items():
            if fs.language is Language.PYTHON:
                self.table.python_modules[fs.module_name] = path
                # Also register the dotted path including a "src." prefix, if any.
                dotted = path[:-3].replace("/", ".") if path.endswith(".py") else path
                self.table.python_modules.setdefault(dotted.removesuffix(".__init__"), path)
            else:
                self.table.js_modules[JS_SOURCE_SUFFIX_RE.sub("", path)] = path

    def _add_file(self, fs: FileSymbols) -> None:
        """Add the file node and one node (plus a DEFINES edge) per symbol in the file."""
        file_node = self.graph.add_node(
            GraphNode(
                id=node_id(NodeKind.FILE, fs.path, FILE_NODE_NAME),
                kind=NodeKind.FILE,
                name=fs.path,
                file=fs.path,
                line_start=1,
                line_end=max(fs.loc, 1),
                meta={"language": fs.language.value, "test": str(fs.is_test_file).lower()},
            )
        )
        self.table.by_qualified_name[(fs.path, MODULE_KEY)] = file_node.id
        handlers = {e.handler for e in fs.endpoints}
        for symbol in fs.symbols:
            kind = KIND_MAP.get(symbol.kind)
            if kind is not None:
                self._add_symbol(fs, symbol, kind, file_node.id, handlers)

    def _add_symbol(
        self, fs: FileSymbols, symbol: Symbol, kind: NodeKind, file_id: str, handlers: set[str]
    ) -> None:
        node = self.graph.add_node(
            GraphNode(
                id=node_id(kind, fs.path, symbol.qualified_name),
                kind=kind,
                name=symbol.qualified_name,
                file=fs.path,
                line_start=symbol.line_start,
                line_end=symbol.line_end,
                meta=_symbol_meta(fs, symbol, handlers),
            )
        )
        self.table.by_qualified_name[(fs.path, symbol.qualified_name)] = node.id
        parent_name = symbol.qualified_name.rpartition(".")[0] or symbol.parent
        parent_id = self.table.node_for(fs.path, parent_name or MODULE_KEY)
        if kind is NodeKind.MODULE:
            parent_id = file_id
        self.graph.add_edge(parent_id or file_id, node.id, EdgeKind.DEFINES)
        if kind is NodeKind.METHOD:
            self.table.methods_by_name.setdefault(symbol.name, []).append(node.id)
        elif kind in (NodeKind.FUNCTION, NodeKind.CLASS) and "." not in symbol.qualified_name:
            self.table.top_level_by_name.setdefault(symbol.name, []).append(node.id)

    # ------------------------------------------------------------------ pass 3-5: edges
    def _add_imports(self, fs: FileSymbols) -> None:
        bindings, imported_files = resolve_imports(self.table, fs)
        self.table.imports[fs.path] = bindings
        source = self.table.module_node(fs.path)
        for path, line in imported_files:
            target = self.table.module_node(path)
            if source and target:
                self.graph.add_edge(source, target, EdgeKind.IMPORTS, line)

    def _add_inheritance(self, fs: FileSymbols) -> None:
        for symbol in fs.symbols:
            class_id = self.table.node_for(fs.path, symbol.qualified_name)
            if symbol.kind is not SymbolKind.CLASS or class_id is None:
                continue
            for base in symbol.bases:
                target = self.resolver.resolve(fs, base, symbol.qualified_name)
                target_node = self.graph.node(target) if target else None
                if target_node is not None and target_node.kind is NodeKind.CLASS:
                    kind = (
                        EdgeKind.IMPLEMENTS
                        if _looks_like_interface(fs, base)
                        else EdgeKind.INHERITS
                    )
                    self.graph.add_edge(class_id, target_node.id, kind, symbol.line_start)

    def _add_endpoints(self, fs: FileSymbols) -> None:
        """Add an ENDPOINT node per route and a ROUTES edge to its handler."""
        for endpoint in fs.endpoints:
            name = f"{endpoint.method} {endpoint.route}"
            endpoint_node = self.graph.add_node(
                GraphNode(
                    id=node_id(NodeKind.ENDPOINT, fs.path, f"{name}::{endpoint.handler}"),
                    kind=NodeKind.ENDPOINT,
                    name=name,
                    file=fs.path,
                    line_start=endpoint.line,
                    line_end=endpoint.line,
                    meta={"method": endpoint.method, "route": endpoint.route},
                )
            )
            handler = self.table.node_for(fs.path, endpoint.handler) or self.resolver.resolve(
                fs, endpoint.handler, MODULE_KEY
            )
            handler_node = self.graph.node(handler) if handler else None
            if handler_node is not None:
                self.graph.add_edge(
                    endpoint_node.id, handler_node.id, EdgeKind.ROUTES, endpoint.line
                )
                handler_node.meta["entrypoint"] = TRUE
                handler_node.meta["endpoint"] = name

    def _add_calls(self, fs: FileSymbols) -> None:
        """Add CALLS edges (and TESTS edges when a test calls non-test code)."""
        for call in fs.calls:
            source = self.table.caller_node(fs.path, call.caller)
            if source is None:
                continue
            target = self.resolver.resolve(fs, call.callee, call.caller)
            target_node = self.graph.node(target) if target else None
            if target is None or target_node is None or target_node.kind not in CODE_KINDS:
                self.unresolved += 1
                continue
            self.resolved += 1
            self.graph.add_edge(source, target, EdgeKind.CALLS, call.line)
            source_node = self.graph.node(source)
            is_test = source_node is not None and source_node.kind is NodeKind.TEST
            if is_test and self.table.is_not_test(target):
                self.graph.add_edge(source, target, EdgeKind.TESTS, call.line)

    def _add_db_operations(self, fs: FileSymbols) -> None:
        """Add DATABASE nodes per table with READS / WRITES edges; mark queries in loops."""
        for operation in fs.db_operations:
            source = self.table.caller_node(fs.path, operation.function)
            if source is None:
                continue
            kind = EdgeKind.WRITES if operation.operation == "write" else EdgeKind.READS
            for table in _tables(operation):
                database = self.graph.add_node(
                    GraphNode(
                        id=node_id(NodeKind.DATABASE, None, table),
                        kind=NodeKind.DATABASE,
                        name=table,
                        meta={"table": table},
                    )
                )
                self.graph.add_edge(source, database.id, kind, operation.line)
            source_node = self.graph.node(source)
            if operation.in_loop and source_node is not None:
                previous = source_node.meta.get("db_in_loop", "")
                source_node.meta["db_in_loop"] = ",".join(
                    filter(None, [previous, str(operation.line)])
                )


def _symbol_meta(fs: FileSymbols, symbol: Symbol, handlers: set[str]) -> dict[str, str]:
    """The string metadata the UI and the verifier read from a symbol node."""
    meta = {"language": fs.language.value}
    if symbol.is_async:
        meta["async"] = TRUE
    if symbol.exported:
        meta["exported"] = TRUE
    if symbol.params:
        meta["params"] = ", ".join(symbol.params)
    if symbol.decorators:
        meta["decorators"] = ", ".join(symbol.decorators)
    if _is_entrypoint(symbol, handlers):
        meta["entrypoint"] = TRUE
    return meta


def _is_entrypoint(symbol: Symbol, handlers: set[str]) -> bool:
    """Route handlers, ``main``, and functions with entry-point decorators."""
    if symbol.qualified_name in handlers or symbol.qualified_name == "__main__":
        return True
    if symbol.name in ENTRY_NAMES:
        return True
    return any(d.split(".")[-1].lower() in ENTRY_DECORATOR_HINTS for d in symbol.decorators if d)


def _looks_like_interface(fs: FileSymbols, base: str) -> bool:
    """TypeScript convention: ``IUserRepo`` is an interface, so the edge is IMPLEMENTS."""
    return (
        fs.language is not Language.PYTHON
        and len(base) > 1
        and base[0] == "I"
        and base[1].isupper()
    )


def _tables(operation: DbOperation) -> list[str]:
    """Table names a database operation touches, or one generic node when unknown."""
    match = TABLE_LIST_RE.search(operation.detail)
    if match is None:
        return [GENERIC_DATABASE]
    return [t.strip() for t in match.group(1).split(",")]
