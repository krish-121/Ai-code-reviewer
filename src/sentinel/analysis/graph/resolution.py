"""Name resolution for the code graph.

Answers two questions for ``builder.py``:

- *imports*: which repository file does ``from app import db`` / ``import "./db"`` point to?
- *calls*: which function or method does ``self.repo.find(...)`` actually call?

Resolution is deliberately conservative: when there is no clear answer, the functions here
return None and no edge is drawn. A missing edge only costs some context; a wrong edge
would mislead the verifier.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from sentinel.core.domain.code import FileSymbols, ImportRef, SymbolKind
from sentinel.core.domain.graph import CodeGraph, EdgeKind, NodeKind
from sentinel.core.domain.models import Language

MODULE_KEY = "<module>"
SELF_NAMES = frozenset({"self", "this", "cls"})
MAX_INHERITANCE_DEPTH = 5
JS_SOURCE_SUFFIX_RE = re.compile(r"\.[cm]?[jt]sx?$")
_NAME_SPLIT_RE = re.compile(r"[._\-/\s]+|(?<=[a-z0-9])(?=[A-Z])")
_FILLER_WORDS = frozenset({"self", "this", "cls", "the"})
MIN_PLURAL_LENGTH = 4  # "users" -> "user", but "bus" stays "bus"

# Names too generic to resolve by "the only definition with this name" — `get`, `run`, ...
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

# local name -> (file it comes from, imported symbol name, or None when a module is bound)
ImportBinding = tuple[str, str | None]


@dataclass
class SymbolTable:
    """Lookup tables filled while nodes are added; read during resolution."""

    graph: CodeGraph
    files: dict[str, FileSymbols]
    # (file path, qualified name) -> node id; MODULE_KEY maps to the file node
    by_qualified_name: dict[tuple[str, str], str] = field(default_factory=dict)
    python_modules: dict[str, str] = field(default_factory=dict)  # dotted name -> path
    js_modules: dict[str, str] = field(default_factory=dict)  # path without suffix -> path
    imports: dict[str, dict[str, ImportBinding]] = field(default_factory=dict)  # per file
    methods_by_name: dict[str, list[str]] = field(default_factory=dict)
    top_level_by_name: dict[str, list[str]] = field(default_factory=dict)

    def node_for(self, path: str, qualified_name: str) -> str | None:
        """Node id of a symbol defined in ``path``."""
        return self.by_qualified_name.get((path, qualified_name))

    def module_node(self, path: str) -> str | None:
        """Node id of the file node for ``path``."""
        return self.node_for(path, MODULE_KEY)

    def caller_node(self, path: str, caller: str) -> str | None:
        """Node for the symbol a call was made from, walking up to the nearest indexed one.

        Calls inside lambdas or nested blocks can be attributed to names that have no
        node of their own; those fall back to their parent, and finally to the file.
        """
        parts = caller.split(".")
        while parts:
            found = self.node_for(path, ".".join(parts))
            if found:
                return found
            parts = parts[:-1]
        return self.module_node(path)

    def is_not_test(self, node_id: str) -> bool:
        """True for nodes that exist and are not tests."""
        node = self.graph.node(node_id)
        return node is not None and node.kind is not NodeKind.TEST


# --------------------------------------------------------------------------- imports


def resolve_imports(
    table: SymbolTable, fs: FileSymbols
) -> tuple[dict[str, ImportBinding], list[tuple[str, int]]]:
    """Resolve every import in ``fs``.

    Returns:
        The names each import binds (local name -> binding), and the repository files
        that are imported, as ``(path, line)`` pairs for IMPORTS edges.
    """
    bindings: dict[str, ImportBinding] = {}
    imported_files: list[tuple[str, int]] = []
    for imp in fs.imports:
        if fs.language is Language.PYTHON:
            target = _bind_python_import(table, fs, imp, bindings, imported_files)
        else:
            target = _bind_js_import(table, fs, imp, bindings)
        if target is not None:
            imported_files.append((target, imp.line))
    return bindings, imported_files


def _bind_python_import(
    table: SymbolTable,
    fs: FileSymbols,
    imp: ImportRef,
    bindings: dict[str, ImportBinding],
    imported_files: list[tuple[str, int]],
) -> str | None:
    target = _python_module_path(table, fs, imp)
    if not imp.names:  # import a.b as c
        if target is not None:
            for local in imp.aliases:
                bindings[local] = (target, None)
        return target
    for local, name in imp.aliases.items():  # from X import a, b
        # `from pkg import submodule` binds a module, not a symbol.
        submodule_ref = ImportRef(module=f"{imp.module}.{name}".strip("."), level=imp.level)
        submodule = _python_module_path(table, fs, submodule_ref)
        if submodule is not None and submodule != target:
            bindings[local] = (submodule, None)
            imported_files.append((submodule, imp.line))
        elif target is not None:
            bindings[local] = (target, name)
    return target


def _bind_js_import(
    table: SymbolTable, fs: FileSymbols, imp: ImportRef, bindings: dict[str, ImportBinding]
) -> str | None:
    target = _js_module_path(table, fs, imp.module)
    if target is not None:
        for local, name in imp.aliases.items():
            bindings[local] = (target, None if name == "*" else name)
    return target


def _python_module_path(table: SymbolTable, fs: FileSymbols, imp: ImportRef) -> str | None:
    """File for a Python import, handling relative imports (``from ..db import x``)."""
    if imp.level == 0:
        return _lookup_python_module(table, imp.module)
    package = fs.module_name.split(".")
    if not fs.path.endswith("__init__.py"):
        package = package[:-1]
    if imp.level > 1:
        package = package[: len(package) - (imp.level - 1)]
    base = ".".join(package)
    target = f"{base}.{imp.module}" if imp.module else base
    return _lookup_python_module(table, target.strip("."))


def _lookup_python_module(table: SymbolTable, dotted: str) -> str | None:
    if dotted in table.python_modules:
        return table.python_modules[dotted]
    # Tolerate src-layout / namespace prefixes: match on a unique suffix.
    matches = {p for m, p in table.python_modules.items() if m.endswith("." + dotted)}
    return matches.pop() if len(matches) == 1 else None


def _js_module_path(table: SymbolTable, fs: FileSymbols, spec: str) -> str | None:
    """File for a JS/TS import specifier; None for third-party packages."""
    if spec.startswith(("@/", "~/")):
        candidates = [f"src/{spec[2:]}", spec[2:]]
    elif spec.startswith("."):
        candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(fs.path), spec))]
    else:
        return None
    for candidate in candidates:
        stem = JS_SOURCE_SUFFIX_RE.sub("", candidate)
        for key in (stem, f"{stem}/index"):
            if key in table.js_modules:
                return table.js_modules[key]
    return None


# --------------------------------------------------------------------------- calls


class CallResolver:
    """Finds the graph node a call expression refers to."""

    def __init__(self, table: SymbolTable) -> None:
        self.table = table

    def resolve(self, fs: FileSymbols, callee: str, caller: str) -> str | None:
        """Node id called by ``callee`` (as written in the source) from inside ``caller``."""
        parts = callee.split(".")
        if len(parts) == 1:
            return self._plain_name(fs, callee, caller)
        head = parts[0]
        if len(parts) == 2 and head in SELF_NAMES:
            cls = self._enclosing_class(fs, caller)
            return self._method_of(cls, parts[1]) if cls else None
        if len(parts) == 2 and head == "super":
            return self._super_method(fs, caller, parts[1])
        found = self._through_import(fs, head, ".".join(parts[1:]))
        if found:
            return found
        local_class = self._local_class(fs, head) if len(parts) == 2 else None
        if local_class:
            return self._method_of(local_class, parts[1])
        return self._by_receiver_name(".".join(parts[:-1]), parts[-1])

    def _plain_name(self, fs: FileSymbols, name: str, caller: str) -> str | None:
        """``f()``: nested def, same-file def, imported name, or a unique repository name."""
        for qualified in (f"{caller}.{name}", name):
            found = self.table.node_for(fs.path, qualified)
            if found:
                return found
        binding = self.table.imports.get(fs.path, {}).get(name)
        if binding is not None:
            target, symbol = binding
            return self._symbol_in(target, symbol) if symbol else None
        candidates = [
            c for c in self.table.top_level_by_name.get(name, []) if self.table.is_not_test(c)
        ]
        if len(candidates) == 1 and name not in COMMON_NAMES:
            return candidates[0]
        return None

    def _through_import(self, fs: FileSymbols, head: str, rest: str) -> str | None:
        """``mod.func()`` / ``mod.Class.method()`` / ``ImportedClass.method()``."""
        binding = self.table.imports.get(fs.path, {}).get(head)
        if binding is None:
            return None
        target, symbol = binding
        return self._symbol_in(target, rest if symbol is None else f"{symbol}.{rest}")

    def _symbol_in(self, path: str, name: str | None) -> str | None:
        """Node for ``name`` defined in ``path``; ``default`` means the default export."""
        if name is None:
            return None
        if name != "default":
            return self.table.node_for(path, name)
        fs = self.table.files.get(path)
        exported = [
            s
            for s in (fs.symbols if fs else [])
            if s.exported and s.kind in (SymbolKind.FUNCTION, SymbolKind.CLASS)
        ]
        return self.table.node_for(path, exported[0].qualified_name) if exported else None

    def _local_class(self, fs: FileSymbols, name: str) -> str | None:
        node_id = self.table.node_for(fs.path, name)
        node = self.table.graph.node(node_id) if node_id else None
        return node.id if node is not None and node.kind is NodeKind.CLASS else None

    def _enclosing_class(self, fs: FileSymbols, caller: str) -> str | None:
        """The class a method belongs to (innermost first)."""
        parts = caller.split(".")
        for length in range(len(parts), 0, -1):
            found = self._local_class(fs, ".".join(parts[:length]))
            if found:
                return found
        return None

    def _method_of(self, class_id: str, method: str, depth: int = 0) -> str | None:
        """``method`` defined on the class or inherited from one of its bases."""
        node = self.table.graph.node(class_id)
        if node is None or node.file is None or depth > MAX_INHERITANCE_DEPTH:
            return None
        found = self.table.node_for(node.file, f"{node.name}.{method}")
        if found:
            return found
        for edge in self.table.graph.out_edges(class_id, [EdgeKind.INHERITS]):
            found = self._method_of(edge.target, method, depth + 1)
            if found:
                return found
        return None

    def _super_method(self, fs: FileSymbols, caller: str, method: str) -> str | None:
        """``super().method()``: look in the base classes only."""
        cls = self._enclosing_class(fs, caller)
        for edge in self.table.graph.out_edges(cls, [EdgeKind.INHERITS]) if cls else []:
            found = self._method_of(edge.target, method)
            if found:
                return found
        return None

    def _by_receiver_name(self, receiver: str, method: str) -> str | None:
        """``user_repo.find()``: pick the ``find`` whose class name best matches ``user_repo``.

        Only answers when one candidate clearly wins (shares more words with the receiver
        than any other candidate).
        """
        candidates = [
            c for c in self.table.methods_by_name.get(method, []) if self.table.is_not_test(c)
        ]
        if len(candidates) == 1 and method not in COMMON_NAMES:
            return candidates[0]
        receiver_words = name_words(receiver)
        if not candidates or not receiver_words:
            return None
        scored = sorted(
            (
                (len(receiver_words & name_words(node.name.rsplit(".", 1)[0])), node.id)
                for node in map(self.table.graph.node, candidates)
                if node is not None
            ),
            reverse=True,
        )
        best_score = scored[0][0] if scored else 0
        runner_up = scored[1][0] if len(scored) > 1 else -1
        return scored[0][1] if best_score > 0 and runner_up < best_score else None


def name_words(name: str) -> set[str]:
    """Lower-case words in an identifier, singularized: ``UserRepos`` -> {"user", "repo"}."""
    words: set[str] = set()
    for part in _NAME_SPLIT_RE.split(name):
        word = part.lower()
        if not word or word in _FILLER_WORDS:
            continue
        is_plural = len(word) >= MIN_PLURAL_LENGTH and word.endswith("s")
        words.add(word[:-1] if is_plural else word)
    return words
