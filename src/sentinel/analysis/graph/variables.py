"""Connect observed accesses to known module variables, never guessed name matches.

Called by the graph builder after import bindings exist. These edges describe lexical
reads/writes, not value propagation, runtime reachability or security taint.
"""

from __future__ import annotations

from sentinel.analysis.graph.resolution import SymbolTable
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import EdgeKind, NodeKind


def add_variable_edges(table: SymbolTable, files: dict[str, FileSymbols]) -> None:
    """Add READS/WRITES edges only when both the owner and variable are known."""
    for fs in files.values():
        for access in fs.variable_accesses:
            target = _variable(table, fs.path, access.name)
            source = table.caller_node(fs.path, access.symbol)
            if target is not None and source is not None:
                kind = EdgeKind.WRITES if access.operation == "write" else EdgeKind.READS
                table.graph.add_edge(source, target, kind, access.line)


def _variable(table: SymbolTable, path: str, name: str) -> str | None:
    parts = name.split(".", 1)
    binding = table.imports.get(path, {}).get(parts[0])
    if binding is None:
        target = table.node_for(path, name)
    else:
        imported_path, imported_name = binding
        if len(parts) == 2:
            if imported_name is not None:
                return None
            imported_name = parts[1]
        target = table.node_for(imported_path, imported_name) if imported_name else None
    node = table.graph.node(target) if target else None
    return target if node is not None and node.kind is NodeKind.VARIABLE else None
