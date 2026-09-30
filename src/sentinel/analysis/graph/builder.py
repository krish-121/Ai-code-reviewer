"""Build a ``CodeGraph`` from per-file ``FileSymbols``.

Resolution is intentionally conservative: a call edge is only added when the target
can be identified with reasonable certainty (same file, explicit import, ``self``/
``this`` method, or a name that is unique in the repository). A missing edge costs
some context; a wrong edge would mislead the verifier.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from sentinel.core.domain.code import FileSymbols, ImportRef, Symbol, SymbolKind
from sentinel.core.domain.graph import CodeGraph, EdgeKind, GraphNode, NodeKind, node_id
from sentinel.core.domain.models import Language

KIND_MAP = {
    SymbolKind.CLASS: NodeKind.CLASS,
    SymbolKind.FUNCTION: NodeKind.FUNCTION,
    SymbolKind.METHOD: NodeKind.METHOD,
    SymbolKind.TEST: NodeKind.TEST,
}
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
ENTRY_DECORATOR_HINTS = (
    "route",
    "command",
    "group",
    "task",
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "websocket",
    "handler",
    "listener",
    "entrypoint",
)
COMMON_NAMES = frozenset(
    """
    get set add append extend update pop items keys values format join split strip replace
    read write close open send map filter reduce push then catch finally log error info
    debug warn warning execute commit query fetch json copy sort remove insert count index
    lower upper startswith endswith encode decode call apply bind toString forEach find
    includes slice splice concat test match exec next run start stop init __init__ to_dict
    dict dumps loads load dump save delete create list all first one render emit on off
    resolve reject sleep wait print len str int float bool isinstance super range enumerate
    zip sorted min max sum any abs hash setattr getattr hasattr type iter repr round id
    vars dir property staticmethod classmethod constructor require expect describe it toBe
    toEqual assert
""".split()
)


@dataclass
class GraphBuildResult:
    graph: CodeGraph
    files: dict[str, FileSymbols]
    unresolved_calls: int = 0
    resolved_calls: int = 0
    symbol_index: dict[tuple[str, str], str] = field(default_factory=dict)


def _tokens(name: str) -> set[str]:
    parts = re.split(r"[._\-/\s]+|(?<=[a-z0-9])(?=[A-Z])", name)
    out: set[str] = set()
    for p in parts:
        p = p.lower()
        if not p or p in ("self", "this", "cls", "the"):
            continue
        out.add(p[:-1] if len(p) > 3 and p.endswith("s") else p)
    return out


class GraphBuilder:
    def __init__(self, files: dict[str, FileSymbols]) -> None:
        self.files = files
        self.graph = CodeGraph()
        self.sym_index: dict[tuple[str, str], str] = {}  # (path, qualified_name) -> node id
        self.py_modules: dict[str, str] = {}
        self.js_paths: dict[str, str] = {}
        self.imports: dict[str, dict[str, tuple[str, str | None]]] = {}
        self.methods_by_name: dict[str, list[str]] = {}
        self.defs_by_name: dict[str, list[str]] = {}
        self.class_bases: dict[str, list[str]] = {}
        self.resolved = 0
        self.unresolved = 0

    # ------------------------------------------------------------------ public
    def build(self) -> GraphBuildResult:
        self._index_modules()
        for fs in self.files.values():
            self._add_file(fs)
        for fs in self.files.values():
            self.imports[fs.path] = self._resolve_imports(fs)
        for fs in self.files.values():
            self._add_inheritance(fs)
        for fs in self.files.values():
            self._add_endpoints(fs)
            self._add_calls(fs)
            self._add_db(fs)
        return GraphBuildResult(
            graph=self.graph,
            files=self.files,
            unresolved_calls=self.unresolved,
            resolved_calls=self.resolved,
            symbol_index=self.sym_index,
        )

    # ------------------------------------------------------------------ indexing
    def _index_modules(self) -> None:
        for path, fs in self.files.items():
            if fs.language is Language.PYTHON:
                mod = fs.module_name
                self.py_modules[mod] = path
                # Also register the dotted path including a "src." prefix, if any.
                full = path[:-3].replace("/", ".") if path.endswith(".py") else path
                self.py_modules.setdefault(full.removesuffix(".__init__"), path)
            else:
                stem = re.sub(r"\.[cm]?[jt]sx?$", "", path)
                self.js_paths[stem] = path

    def _add_file(self, fs: FileSymbols) -> None:
        file_node = self.graph.add_node(
            GraphNode(
                id=node_id(NodeKind.FILE, fs.path, "<file>"),
                kind=NodeKind.FILE,
                name=fs.path,
                file=fs.path,
                line_start=1,
                line_end=max(fs.loc, 1),
                meta={"language": fs.language.value, "test": str(fs.is_test_file).lower()},
            )
        )
        self.sym_index[(fs.path, "<module>")] = file_node.id
        endpoint_handlers = {e.handler for e in fs.endpoints}
        for sym in fs.symbols:
            kind = KIND_MAP.get(sym.kind)
            if kind is None:
                continue
            meta = {"language": fs.language.value}
            if sym.is_async:
                meta["async"] = "true"
            if sym.exported:
                meta["exported"] = "true"
            if sym.params:
                meta["params"] = ", ".join(sym.params)
            if sym.decorators:
                meta["decorators"] = ", ".join(sym.decorators)
            if self._is_entry(sym, endpoint_handlers):
                meta["entrypoint"] = "true"
            node = self.graph.add_node(
                GraphNode(
                    id=node_id(kind, fs.path, sym.qualified_name),
                    kind=kind,
                    name=sym.qualified_name,
                    file=fs.path,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    meta=meta,
                )
            )
            self.sym_index[(fs.path, sym.qualified_name)] = node.id
            parent_id = self.sym_index.get((fs.path, sym.parent)) if sym.parent else None
            self.graph.add_edge(parent_id or file_node.id, node.id, EdgeKind.DEFINES)
            if kind is NodeKind.METHOD:
                self.methods_by_name.setdefault(sym.name, []).append(node.id)
            elif kind in (NodeKind.FUNCTION, NodeKind.CLASS) and "." not in sym.qualified_name:
                self.defs_by_name.setdefault(sym.name, []).append(node.id)
            if kind is NodeKind.CLASS:
                self.class_bases[node.id] = sym.bases

    @staticmethod
    def _is_entry(sym: Symbol, handlers: set[str]) -> bool:
        if sym.qualified_name in handlers or sym.qualified_name == "__main__":
            return True
        if sym.name == "main":
            return True
        return any(d.split(".")[-1].lower() in ENTRY_DECORATOR_HINTS for d in sym.decorators if d)

    # ------------------------------------------------------------------ imports
    def _resolve_python_module(self, fs: FileSymbols, imp: ImportRef) -> str | None:
        if imp.level == 0:
            return self._lookup_py(imp.module)
        package = fs.module_name.split(".")
        if not fs.path.endswith("__init__.py"):
            package = package[:-1]
        if imp.level > 1:
            package = package[: len(package) - (imp.level - 1)]
        base = ".".join(package)
        target = f"{base}.{imp.module}" if imp.module else base
        return self._lookup_py(target.strip("."))

    def _lookup_py(self, dotted: str) -> str | None:
        if dotted in self.py_modules:
            return self.py_modules[dotted]
        # Tolerate src-layout / namespace prefixes: match on unique suffix.
        matches = [p for m, p in self.py_modules.items() if m.endswith("." + dotted)]
        return matches[0] if len(set(matches)) == 1 else None

    def _resolve_js_module(self, fs: FileSymbols, spec: str) -> str | None:
        if spec.startswith(("@/", "~/")):
            candidates = [f"src/{spec[2:]}", spec[2:]]
        elif spec.startswith("."):
            candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(fs.path), spec))]
        else:
            return None  # third-party package
        for cand in candidates:
            stem = re.sub(r"\.[cm]?[jt]sx?$", "", cand)
            if stem in self.js_paths:
                return self.js_paths[stem]
            if f"{stem}/index" in self.js_paths:
                return self.js_paths[f"{stem}/index"]
        return None

    def _resolve_imports(self, fs: FileSymbols) -> dict[str, tuple[str, str | None]]:
        """local name -> (target file, imported symbol name or None for a module alias)."""
        table: dict[str, tuple[str, str | None]] = {}
        file_node = self.sym_index[(fs.path, "<module>")]
        for imp in fs.imports:
            if fs.language is Language.PYTHON:
                target = self._resolve_python_module(fs, imp)
                if imp.names:  # from X import a, b
                    for local, name in imp.aliases.items():
                        # `from pkg import submodule` binds a module, not a symbol.
                        sub = self._resolve_python_module(
                            fs,
                            ImportRef(module=f"{imp.module}.{name}".strip("."), level=imp.level),
                        )
                        if sub is not None and sub != target:
                            table[local] = (sub, None)
                            self.graph.add_edge(
                                file_node,
                                self.sym_index[(sub, "<module>")],
                                EdgeKind.IMPORTS,
                                imp.line,
                            )
                        elif target is not None:
                            table[local] = (target, name)
                elif target is not None:  # import a.b as c
                    for local in imp.aliases:
                        table[local] = (target, None)
            else:
                target = self._resolve_js_module(fs, imp.module)
                if target is not None:
                    for local, name in imp.aliases.items():
                        table[local] = (target, None if name == "*" else name)
            if target is not None and (target, "<module>") in self.sym_index:
                self.graph.add_edge(
                    file_node, self.sym_index[(target, "<module>")], EdgeKind.IMPORTS, imp.line
                )
        return table

    # ------------------------------------------------------------------ resolution
    def _symbol_in(self, path: str, name: str | None) -> str | None:
        if name is None:
            return None
        if name == "default":
            fs = self.files.get(path)
            if fs:
                for s in fs.symbols:
                    if s.exported and s.kind in (SymbolKind.FUNCTION, SymbolKind.CLASS):
                        return self.sym_index.get((path, s.qualified_name))
            return None
        return self.sym_index.get((path, name))

    def _class_method(self, class_id: str, method: str, depth: int = 0) -> str | None:
        node = self.graph.node(class_id)
        if node is None or node.file is None or depth > 5:
            return None
        found = self.sym_index.get((node.file, f"{node.name}.{method}"))
        if found:
            return found
        for base_edge in self.graph.out_edges(class_id, [EdgeKind.INHERITS]):
            found = self._class_method(base_edge.target, method, depth + 1)
            if found:
                return found
        return None

    def _resolve_name(self, fs: FileSymbols, name: str, caller: str) -> str | None:
        # nested definition inside the caller, then same-file top level
        for qn in (f"{caller}.{name}", name):
            found = self.sym_index.get((fs.path, qn))
            if found:
                return found
        imported = self.imports.get(fs.path, {}).get(name)
        if imported is not None:
            target, sym = imported
            return self._symbol_in(target, sym) if sym else None
        candidates = [c for c in self.defs_by_name.get(name, []) if self._not_test(c)]
        if len(candidates) == 1 and name not in COMMON_NAMES:
            return candidates[0]
        return None

    def _not_test(self, nid: str) -> bool:
        node = self.graph.node(nid)
        return node is not None and node.kind is not NodeKind.TEST

    def _enclosing_class(self, fs: FileSymbols, caller: str) -> str | None:
        parts = caller.split(".")
        for i in range(len(parts), 0, -1):
            qn = ".".join(parts[:i])
            nid = self.sym_index.get((fs.path, qn))
            node = self.graph.node(nid) if nid else None
            if node is not None and node.kind is NodeKind.CLASS:
                return node.id
        return None

    def resolve_callee(self, fs: FileSymbols, callee: str, caller: str) -> str | None:
        parts = callee.split(".")
        if len(parts) == 1:
            return self._resolve_name(fs, parts[0], caller)
        head, rest = parts[0], parts[1:]
        if head in ("self", "this", "cls") and len(parts) == 2:
            cls = self._enclosing_class(fs, caller)
            return self._class_method(cls, rest[0]) if cls else None
        if head == "super" and len(parts) == 2:
            cls = self._enclosing_class(fs, caller)
            if cls:
                for e in self.graph.out_edges(cls, [EdgeKind.INHERITS]):
                    found = self._class_method(e.target, rest[0])
                    if found:
                        return found
            return None
        imported = self.imports.get(fs.path, {}).get(head)
        if imported is not None:
            target, sym = imported
            if sym is None:  # module alias: mod.func / mod.Class.method
                found = self._symbol_in(target, ".".join(rest))
                if found:
                    return found
            else:  # imported class/object: Class.method
                found = self._symbol_in(target, f"{sym}.{'.'.join(rest)}")
                if found:
                    return found
        local = self.sym_index.get((fs.path, head))
        if local is not None and self.graph.node(local) and len(parts) == 2:
            node = self.graph.node(local)
            if node is not None and node.kind is NodeKind.CLASS:
                return self._class_method(local, rest[0])
        return self._resolve_method_by_receiver(".".join(parts[:-1]), parts[-1])

    def _resolve_method_by_receiver(self, receiver: str, method: str) -> str | None:
        candidates = [c for c in self.methods_by_name.get(method, []) if self._not_test(c)]
        if not candidates:
            return None
        if len(candidates) == 1 and method not in COMMON_NAMES:
            return candidates[0]
        recv = _tokens(receiver)
        if not recv:
            return None
        scored: list[tuple[int, str]] = []
        for c in candidates:
            node = self.graph.node(c)
            if node is None:
                continue
            cls_name = node.name.rsplit(".", 1)[0]
            scored.append((len(recv & _tokens(cls_name)), c))
        scored.sort(reverse=True)
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return scored[0][1]
        return None

    # ------------------------------------------------------------------ edges
    def _caller_node(self, fs: FileSymbols, caller: str) -> str | None:
        found = self.sym_index.get((fs.path, caller))
        if found:
            return found
        # Calls inside lambdas/nested blocks attributed to an unindexed name: walk up.
        parts = caller.split(".")
        while len(parts) > 1:
            parts = parts[:-1]
            found = self.sym_index.get((fs.path, ".".join(parts)))
            if found:
                return found
        return self.sym_index.get((fs.path, "<module>"))

    def _add_calls(self, fs: FileSymbols) -> None:
        for call in fs.calls:
            src = self._caller_node(fs, call.caller)
            if src is None:
                continue
            target = self.resolve_callee(fs, call.callee, call.caller)
            if target is None:
                self.unresolved += 1
                continue
            self.resolved += 1
            self.graph.add_edge(src, target, EdgeKind.CALLS, call.line)
            src_node = self.graph.node(src)
            if src_node is not None and src_node.kind is NodeKind.TEST and self._not_test(target):
                self.graph.add_edge(src, target, EdgeKind.TESTS, call.line)

    def _add_inheritance(self, fs: FileSymbols) -> None:
        for sym in fs.symbols:
            if sym.kind is not SymbolKind.CLASS:
                continue
            cls_id = self.sym_index.get((fs.path, sym.qualified_name))
            if cls_id is None:
                continue
            for base in sym.bases:
                target = self.resolve_callee(fs, base, sym.qualified_name)
                target_node = self.graph.node(target) if target else None
                if target is not None and target_node and target_node.kind is NodeKind.CLASS:
                    kind = EdgeKind.INHERITS
                    if (
                        fs.language is not Language.PYTHON
                        and base.startswith("I")
                        and (len(base) > 1 and base[1].isupper())
                    ):
                        kind = EdgeKind.IMPLEMENTS
                    self.graph.add_edge(cls_id, target, kind, sym.line_start)

    def _add_endpoints(self, fs: FileSymbols) -> None:
        for ep in fs.endpoints:
            ep_node = self.graph.add_node(
                GraphNode(
                    id=node_id(NodeKind.ENDPOINT, None, f"{ep.method} {ep.route}"),
                    kind=NodeKind.ENDPOINT,
                    name=f"{ep.method} {ep.route}",
                    file=fs.path,
                    line_start=ep.line,
                    line_end=ep.line,
                    meta={"method": ep.method, "route": ep.route},
                )
            )
            handler = self.sym_index.get((fs.path, ep.handler)) or self.resolve_callee(
                fs, ep.handler, "<module>"
            )
            if handler is not None:
                self.graph.add_edge(ep_node.id, handler, EdgeKind.ROUTES, ep.line)
                handler_node = self.graph.node(handler)
                if handler_node is not None:
                    handler_node.meta["entrypoint"] = "true"
                    handler_node.meta["endpoint"] = ep_node.name

    def _add_db(self, fs: FileSymbols) -> None:
        for op in fs.db_operations:
            src = self._caller_node(fs, op.function)
            if src is None:
                continue
            m = re.search(r"\[([^\]]+)\]", op.detail)
            tables = [t.strip() for t in m.group(1).split(",")] if m else ["database"]
            for table in tables:
                db = self.graph.add_node(
                    GraphNode(
                        id=node_id(NodeKind.DATABASE, None, table),
                        kind=NodeKind.DATABASE,
                        name=table,
                        meta={"table": table},
                    )
                )
                kind = EdgeKind.WRITES if op.operation == "write" else EdgeKind.READS
                self.graph.add_edge(src, db.id, kind, op.line)
            if op.in_loop:
                node = self.graph.node(src)
                if node is not None:
                    lines = node.meta.get("db_in_loop", "")
                    node.meta["db_in_loop"] = ",".join(filter(None, [lines, str(op.line)]))


def build_graph(files: dict[str, FileSymbols]) -> GraphBuildResult:
    return GraphBuilder(files).build()
