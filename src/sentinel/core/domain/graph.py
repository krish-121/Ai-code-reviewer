"""A lightweight, in-memory code graph.

Not a compiler-grade semantic graph: nodes are files, symbols, endpoints and data
stores; edges are structural relationships the language analyzers can observe. It is
"enough structure" to answer the questions the context engine and the verifier ask:
who calls this, what does it call, is it reachable from an entry point, is it tested.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, Field


class NodeKind(StrEnum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    TEST = "test"
    ENDPOINT = "endpoint"
    DATABASE = "database"


class EdgeKind(StrEnum):
    IMPORTS = "imports"
    CALLS = "calls"
    DEFINES = "defines"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    TESTS = "tests"
    READS = "reads"
    WRITES = "writes"
    ROUTES = "routes"


CODE_KINDS = frozenset({NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.TEST, NodeKind.CLASS})


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    meta: dict[str, str] = Field(default_factory=dict)

    def contains(self, file: str, line: int) -> bool:
        return (
            self.file == file
            and self.line_start is not None
            and self.line_end is not None
            and self.line_start <= line <= self.line_end
        )


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: EdgeKind
    line: int | None = None


def node_id(kind: NodeKind, file: str | None, name: str) -> str:
    return f"{kind.value}:{file or ''}::{name}"


class CodeGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._out: dict[str, list[GraphEdge]] = {}
        self._in: dict[str, list[GraphEdge]] = {}
        self._edge_keys: set[tuple[str, str, EdgeKind]] = set()

    # ------------------------------------------------------------------ building
    def add_node(self, node: GraphNode) -> GraphNode:
        existing = self._nodes.get(node.id)
        if existing is not None:
            return existing
        self._nodes[node.id] = node
        self._out.setdefault(node.id, [])
        self._in.setdefault(node.id, [])
        return node

    def add_edge(self, source: str, target: str, kind: EdgeKind, line: int | None = None) -> None:
        if source not in self._nodes or target not in self._nodes or source == target:
            return
        key = (source, target, kind)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        edge = GraphEdge(source=source, target=target, kind=kind, line=line)
        self._out[source].append(edge)
        self._in[target].append(edge)

    # ------------------------------------------------------------------ queries
    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    @property
    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[GraphEdge]:
        return [e for edges in self._out.values() for e in edges]

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def out_edges(self, node_id: str, kinds: Iterable[EdgeKind] | None = None) -> list[GraphEdge]:
        allowed = set(kinds) if kinds is not None else None
        return [e for e in self._out.get(node_id, []) if allowed is None or e.kind in allowed]

    def in_edges(self, node_id: str, kinds: Iterable[EdgeKind] | None = None) -> list[GraphEdge]:
        allowed = set(kinds) if kinds is not None else None
        return [e for e in self._in.get(node_id, []) if allowed is None or e.kind in allowed]

    def callers(self, node_id: str) -> list[GraphNode]:
        return [self._nodes[e.source] for e in self.in_edges(node_id, [EdgeKind.CALLS])]

    def callees(self, node_id: str) -> list[GraphNode]:
        return [self._nodes[e.target] for e in self.out_edges(node_id, [EdgeKind.CALLS])]

    def nodes_in_file(self, path: str) -> list[GraphNode]:
        return [n for n in self._nodes.values() if n.file == path]

    def find_by_name(self, name: str) -> list[GraphNode]:
        short = name.split(".")[-1].rstrip("()")
        return [
            n
            for n in self._nodes.values()
            if n.kind in CODE_KINDS and (n.name == name or n.name.split(".")[-1] == short)
        ]

    def enclosing(self, file: str, line: int) -> GraphNode | None:
        """Innermost function/method/class node containing ``file:line``."""
        candidates = [
            n for n in self._nodes.values() if n.kind in CODE_KINDS and n.contains(file, line)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda n: (n.line_end or 0) - (n.line_start or 0))

    def is_entrypoint(self, node: GraphNode) -> bool:
        if node.kind in (NodeKind.ENDPOINT, NodeKind.TEST):
            return True
        if node.meta.get("entrypoint") == "true" or node.meta.get("exported") == "true":
            return True
        return node.name in ("main", "__main__", "handler", "lambda_handler")

    def path_from_entrypoint(self, node_id: str, max_depth: int = 8) -> list[GraphNode] | None:
        """Reverse BFS over CALLS/ROUTES edges to the nearest entry point.

        Returns the path entrypoint -> ... -> node, or None if the node is unreachable.
        Test nodes are only used as a last resort: code reachable only from tests is
        reported as such.
        """
        start = self._nodes.get(node_id)
        if start is None:
            return None
        found_test_path: list[GraphNode] | None = None
        parents: dict[str, str | None] = {node_id: None}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while queue:
            current, depth = queue.popleft()
            node = self._nodes[current]
            if self.is_entrypoint(node):
                path = self._unwind(parents, current)
                routes = self.in_edges(current, [EdgeKind.ROUTES])
                if routes and node.kind is not NodeKind.ENDPOINT:
                    path.insert(0, self._nodes[routes[0].source])
                if node.kind is not NodeKind.TEST:
                    return path
                found_test_path = found_test_path or path
            if depth >= max_depth:
                continue
            for edge in self.in_edges(current, [EdgeKind.CALLS, EdgeKind.ROUTES]):
                if edge.source not in parents:
                    parents[edge.source] = current
                    queue.append((edge.source, depth + 1))
        return found_test_path

    def _unwind(self, parents: dict[str, str | None], end: str) -> list[GraphNode]:
        path: list[GraphNode] = []
        cur: str | None = end
        while cur is not None:
            path.append(self._nodes[cur])
            cur = parents[cur]
        return path  # already ordered entrypoint -> target because we walked in reverse

    def call_path(self, source_id: str, target_id: str, max_depth: int = 6) -> list[GraphNode]:
        """Shortest CALLS path from source to target (empty list when none)."""
        if source_id not in self._nodes or target_id not in self._nodes:
            return []
        parents: dict[str, str | None] = {source_id: None}
        queue: deque[tuple[str, int]] = deque([(source_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if current == target_id:
                path = self._unwind(parents, current)
                return list(reversed(path))
            if depth >= max_depth:
                continue
            for edge in self.out_edges(current, [EdgeKind.CALLS]):
                if edge.target not in parents:
                    parents[edge.target] = current
                    queue.append((edge.target, depth + 1))
        return []

    def tests_for(self, node_id: str, max_depth: int = 3) -> list[GraphNode]:
        """Tests that exercise a node directly (TESTS edge) or through a short call chain."""
        found: dict[str, GraphNode] = {}
        for e in self.in_edges(node_id, [EdgeKind.TESTS]):
            found[e.source] = self._nodes[e.source]
        seen = {node_id}
        frontier = [node_id]
        for _ in range(max_depth):
            nxt: list[str] = []
            for nid in frontier:
                for e in self.in_edges(nid, [EdgeKind.CALLS]):
                    src = self._nodes[e.source]
                    if src.kind is NodeKind.TEST:
                        found[src.id] = src
                    if e.source not in seen:
                        seen.add(e.source)
                        nxt.append(e.source)
            frontier = nxt
        return list(found.values())

    def neighborhood(self, node_ids: Iterable[str], depth: int = 1) -> set[str]:
        keep = {n for n in node_ids if n in self._nodes}
        frontier = set(keep)
        for _ in range(depth):
            nxt: set[str] = set()
            for nid in frontier:
                for e in self._out.get(nid, []):
                    if e.kind is not EdgeKind.DEFINES:
                        nxt.add(e.target)
                for e in self._in.get(nid, []):
                    if e.kind is not EdgeKind.DEFINES:
                        nxt.add(e.source)
            nxt -= keep
            keep |= nxt
            frontier = nxt
        return keep

    def subgraph(self, node_ids: Iterable[str]) -> CodeGraph:
        keep = set(node_ids)
        sub = CodeGraph()
        for nid in keep:
            node = self._nodes.get(nid)
            if node is not None:
                sub.add_node(node)
        for e in self.edges:
            if e.source in keep and e.target in keep:
                sub.add_edge(e.source, e.target, e.kind, e.line)
        return sub

    # ------------------------------------------------------------------ serialization
    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [n.model_dump(mode="json") for n in self._nodes.values()],
            "edges": [e.model_dump(mode="json") for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CodeGraph:
        graph = cls()
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("graph data must contain 'nodes' and 'edges' lists")
        for raw in nodes:
            graph.add_node(GraphNode.model_validate(raw))
        for raw in edges:
            e = GraphEdge.model_validate(raw)
            graph.add_edge(e.source, e.target, e.kind, e.line)
        return graph
