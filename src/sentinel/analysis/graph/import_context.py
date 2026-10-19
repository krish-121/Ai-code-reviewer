"""Select explicitly imported repository data definitions for review context.

The context engine calls this after graph construction. A type used only in an
annotation is not a callee, but its fields can define the contract of changed code.
Follow resolved import edges and exact imported names; never guess from a global
name match or traverse external packages. The caller still budgets and redacts code.
"""

from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import CodeGraph, EdgeKind, GraphNode, NodeKind

DATA_KINDS = frozenset({NodeKind.CLASS, NodeKind.VARIABLE})
MODULE_KINDS = frozenset({NodeKind.FILE, NodeKind.MODULE})


def imported_data_nodes(
    graph: CodeGraph, symbols: dict[str, FileSymbols], path: str, *, limit: int = 6
) -> list[GraphNode]:
    """Return bounded named data imports, including aliases, from resolved local files."""
    source = symbols.get(path)
    if source is None or limit <= 0:
        return []
    found: dict[str, GraphNode] = {}
    for module in graph.nodes_in_file(path):
        if module.kind not in MODULE_KINDS:
            continue
        for edge in graph.out_edges(module.id, [EdgeKind.IMPORTS]):
            target = graph.node(edge.target)
            if target is None or target.file is None:
                continue
            names = {
                name
                for reference in source.imports
                if reference.line == edge.line
                for name in [*reference.names, *reference.aliases.values()]
            }
            for definition in graph.nodes_in_file(target.file):
                if definition.kind in DATA_KINDS and definition.name in names:
                    found[definition.id] = definition
                    if len(found) >= limit:
                        return list(found.values())
    return list(found.values())
