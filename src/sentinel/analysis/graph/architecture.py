"""The small subgraph shown in the web UI's Architecture tab.

Called by ``ContextEngine.build`` (``context.py``). A whole-repository graph is far too
big to draw, so this keeps only what explains the change: the changed symbols, the paths
from entry points that reach them, their direct neighbours, and the endpoints routing to
anything kept.
"""

from __future__ import annotations

from sentinel.core.domain.graph import SOURCE_KINDS, CodeGraph, EdgeKind, GraphNode, NodeKind

DEFAULT_MAX_NODES = 48
FLOW_EDGES = (EdgeKind.CALLS, EdgeKind.ROUTES, EdgeKind.READS, EdgeKind.WRITES, EdgeKind.TESTS)
HIDDEN_KINDS = frozenset({NodeKind.FILE, NodeKind.MODULE})
# Lower rank = kept first when the node budget runs out.
KIND_RANK = {
    NodeKind.ENDPOINT: 0,
    NodeKind.DATABASE: 1,
    NodeKind.FUNCTION: 2,
    NodeKind.METHOD: 2,
    NodeKind.CLASS: 3,
    NodeKind.TEST: 4,
    NodeKind.VARIABLE: 3,
}
UNKNOWN_RANK = 9
CHANGED_FLAG = "changed"


def architecture_subgraph(
    graph: CodeGraph, changed_ids: set[str], max_nodes: int = DEFAULT_MAX_NODES
) -> CodeGraph:
    """The changed symbols, the paths that reach them and their direct neighbours.

    Changed nodes get ``meta["changed"] = "true"`` so the UI can outline them.
    """
    focus = {
        nid for nid in changed_ids if (n := graph.node(nid)) is not None and n.kind in SOURCE_KINDS
    }
    max_nodes = max(0, max_nodes)
    keep = sorted(focus)[:max_nodes]
    for group in (_entry_paths(graph, focus), _neighbours(graph, focus)):
        _add_by_rank(graph, keep, group, max_nodes)
    _add_routing_endpoints(graph, keep, max_nodes)
    sub = graph.subgraph(keep)
    for nid in focus:
        node = sub.node(nid)
        if node is not None:
            node.meta[CHANGED_FLAG] = "true"
    return sub


def _entry_paths(graph: CodeGraph, focus: set[str]) -> set[str]:
    """Every node on the path from the nearest entry point to a focus node."""
    return {node.id for nid in focus for node in graph.path_from_entrypoint(nid) or []}


def _neighbours(graph: CodeGraph, focus: set[str]) -> set[str]:
    """Nodes one CALLS/ROUTES/READS/WRITES/TESTS edge away from a focus node."""
    found: set[str] = set()
    for nid in focus:
        found.update(e.target for e in graph.out_edges(nid, FLOW_EDGES))
        found.update(e.source for e in graph.in_edges(nid, FLOW_EDGES))
    return found


def _add_by_rank(graph: CodeGraph, keep: list[str], group: set[str], max_nodes: int) -> None:
    """Append nodes from ``group`` (endpoints first) until the budget is used up."""
    for nid in sorted(group - set(keep), key=lambda i: (_rank(graph.node(i)), i)):
        node = graph.node(nid)
        if node is None or node.kind in HIDDEN_KINDS:
            continue
        if len(keep) >= max_nodes:
            return
        keep.append(nid)


def _add_routing_endpoints(graph: CodeGraph, keep: list[str], max_nodes: int) -> None:
    """Endpoints that route to anything kept, so every entry point is visible."""
    for nid in list(keep):
        for edge in graph.in_edges(nid, [EdgeKind.ROUTES]):
            if edge.source not in keep and len(keep) < max_nodes:
                keep.append(edge.source)


def _rank(node: GraphNode | None) -> int:
    return UNKNOWN_RANK if node is None else KIND_RANK.get(node.kind, UNKNOWN_RANK)
