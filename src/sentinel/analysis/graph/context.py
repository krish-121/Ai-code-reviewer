"""Context engine: pick the surrounding code the reviewer (human or AI) needs.

For every changed function/class it gathers the full changed body, its callers (around
the call site), its callees, tests that exercise it, the path from the nearest entry
point, and the data stores it touches — then fits that into a character budget by
priority. It never sends the whole repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.analysis.diff.secrets import redact_text
from sentinel.core.domain.ai import ContextBlock
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import (
    CODE_KINDS,
    CodeGraph,
    EdgeKind,
    GraphNode,
    NodeKind,
    node_id,
)
from sentinel.core.domain.models import ChangeSet, FileChange, LineKind

TIER_CHANGED, TIER_CALLER, TIER_CALLEE, TIER_TEST, TIER_PATH, TIER_IMPORT = range(6)


@dataclass
class ChangedSymbol:
    node_id: str
    file: str
    name: str
    kind: NodeKind
    changed_lines: list[int]


@dataclass
class ContextBundle:
    blocks: list[ContextBlock]
    changed_symbols: list[ChangedSymbol]
    call_paths: dict[str, list[str]]
    stats: dict[str, int]
    truncated: bool
    subgraph: CodeGraph
    redactions: int = 0
    dropped: list[str] = field(default_factory=list)


@dataclass
class _Candidate:
    tier: int
    block: ContextBlock


class ContextEngine:
    def __init__(
        self,
        graph: CodeGraph,
        sources: dict[str, str],
        symbols: dict[str, FileSymbols] | None = None,
        *,
        max_chars: int = 60_000,
        max_callers: int = 4,
        max_callees: int = 6,
        max_tests: int = 3,
        max_graph_nodes: int = 80,
    ) -> None:
        self.graph = graph
        self.sources = sources
        self.symbols = symbols or {}
        self.max_chars = max_chars
        self.max_callers = max_callers
        self.max_callees = max_callees
        self.max_tests = max_tests
        self.max_graph_nodes = max_graph_nodes
        self._lines_cache: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ helpers
    def _lines(self, path: str) -> list[str]:
        if path not in self._lines_cache:
            self._lines_cache[path] = self.sources.get(path, "").splitlines()
        return self._lines_cache[path]

    def snippet(self, path: str, start: int, end: int) -> str:
        lines = self._lines(path)
        start = max(1, start)
        end = min(len(lines), end)
        width = len(str(end))
        return "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1))

    def _symbol_window(self, node: GraphNode, focus: list[int], cap: int) -> tuple[int, int]:
        start = node.line_start or 1
        end = node.line_end or start
        if end - start + 1 <= cap:
            return start, end
        if focus:
            lo = max(start, min(focus) - cap // 3)
            return lo, min(end, lo + cap - 1)
        return start, start + cap - 1

    # ------------------------------------------------------------------ changed symbols
    def changed_symbols(self, changeset: ChangeSet) -> list[ChangedSymbol]:
        found: dict[str, ChangedSymbol] = {}
        for change in changeset.reviewable():
            for line in sorted(change.added_lines()):
                node = self.graph.enclosing(change.path, line)
                if node is None:
                    node = self.graph.node(node_id(NodeKind.FILE, change.path, "<file>"))
                    if node is None:
                        continue
                entry = found.setdefault(
                    node.id,
                    ChangedSymbol(node.id, change.path, node.name, node.kind, []),
                )
                entry.changed_lines.append(line)
            # Removed-only hunks still change behaviour of the enclosing symbol.
            for hunk in change.hunks:
                if hunk.new_count and not any(ln.kind is LineKind.ADDED for ln in hunk.lines):
                    node = self.graph.enclosing(change.path, hunk.new_start)
                    if node is not None:
                        found.setdefault(
                            node.id, ChangedSymbol(node.id, change.path, node.name, node.kind, [])
                        )
        return list(found.values())

    # ------------------------------------------------------------------ build
    def build(self, changeset: ChangeSet) -> ContextBundle:
        changed = self.changed_symbols(changeset)
        changed_ids = {c.node_id for c in changed}
        candidates: list[_Candidate] = []
        call_paths: dict[str, list[str]] = {}

        for cs in changed:
            node = self.graph.node(cs.node_id)
            if node is None:
                continue
            if node.kind is NodeKind.FILE:
                change = changeset.get(cs.file)
                if change is not None:
                    candidates.extend(self._module_level_blocks(change, cs.changed_lines))
                continue
            lo, hi = self._symbol_window(node, cs.changed_lines, cap=160)
            candidates.append(
                _Candidate(
                    TIER_CHANGED,
                    ContextBlock(
                        kind="changed",
                        file=cs.file,
                        symbol=node.name,
                        line_start=lo,
                        line_end=hi,
                        code=self.snippet(cs.file, lo, hi),
                        reason="changed in this diff",
                    ),
                )
            )
            candidates.extend(self._caller_blocks(node, changed_ids))
            candidates.extend(self._callee_blocks(node, changed_ids))
            candidates.extend(self._test_blocks(node))
            path = self.graph.path_from_entrypoint(node.id)
            if path and len(path) > 1:
                names = [self._label(n) for n in path]
                call_paths[node.id] = names
                candidates.append(
                    _Candidate(
                        TIER_PATH,
                        ContextBlock(
                            kind="endpoint",
                            file=cs.file,
                            symbol=node.name,
                            line_start=node.line_start or 1,
                            line_end=node.line_start or 1,
                            code="Reachable via: " + " -> ".join(names),
                            reason="nearest entry point",
                        ),
                    )
                )
            data = self._data_access(node)
            if data:
                candidates.append(
                    _Candidate(
                        TIER_PATH,
                        ContextBlock(
                            kind="data",
                            file=cs.file,
                            symbol=node.name,
                            line_start=node.line_start or 1,
                            line_end=node.line_start or 1,
                            code=data,
                            reason="data stores touched",
                        ),
                    )
                )

        for change in changeset.reviewable():
            imp = self._import_block(change)
            if imp is not None:
                candidates.append(imp)

        blocks, truncated, dropped = self._fit(candidates)
        redactions = 0
        for b in blocks:
            b.code, n = redact_text(b.code)
            redactions += n
        stats: dict[str, int] = {}
        for b in blocks:
            stats[b.kind] = stats.get(b.kind, 0) + 1
        stats["chars"] = sum(len(b.code) for b in blocks)
        stats["changed_symbols"] = len(changed)
        return ContextBundle(
            blocks=blocks,
            changed_symbols=changed,
            call_paths=call_paths,
            stats=stats,
            truncated=truncated,
            subgraph=self.ui_subgraph(changed_ids),
            redactions=redactions,
            dropped=dropped,
        )

    def _label(self, node: GraphNode) -> str:
        if node.kind in (NodeKind.ENDPOINT, NodeKind.DATABASE):
            return node.name
        return f"{node.name}()" if node.kind is not NodeKind.CLASS else node.name

    def _module_level_blocks(self, change: FileChange, lines: list[int]) -> list[_Candidate]:
        out: list[_Candidate] = []
        for lo, hi in _cluster(sorted(lines), gap=6):
            s, e = max(1, lo - 3), hi + 3
            out.append(
                _Candidate(
                    TIER_CHANGED,
                    ContextBlock(
                        kind="changed",
                        file=change.path,
                        symbol=None,
                        line_start=s,
                        line_end=min(e, len(self._lines(change.path)) or e),
                        code=self.snippet(change.path, s, e),
                        reason="module-level change",
                    ),
                )
            )
        return out

    def _caller_blocks(self, node: GraphNode, changed_ids: set[str]) -> list[_Candidate]:
        edges = self.graph.in_edges(node.id, [EdgeKind.CALLS])
        # Production callers before tests; tests get their own tier.
        edges.sort(key=lambda e: self.graph.node(e.source).kind is NodeKind.TEST)  # type: ignore[union-attr]
        out: list[_Candidate] = []
        for e in edges:
            caller = self.graph.node(e.source)
            if caller is None or caller.id in changed_ids or caller.kind is NodeKind.TEST:
                continue
            if caller.file is None or e.line is None:
                continue
            lo = max(caller.line_start or 1, e.line - 10)
            hi = min(caller.line_end or e.line, e.line + 8)
            out.append(
                _Candidate(
                    TIER_CALLER,
                    ContextBlock(
                        kind="caller",
                        file=caller.file,
                        symbol=caller.name,
                        line_start=lo,
                        line_end=hi,
                        code=self.snippet(caller.file, lo, hi),
                        reason=f"calls {node.name} at line {e.line}",
                    ),
                )
            )
            if len(out) >= self.max_callers:
                break
        return out

    def _callee_blocks(self, node: GraphNode, changed_ids: set[str]) -> list[_Candidate]:
        out: list[_Candidate] = []
        for callee in self.graph.callees(node.id):
            if callee.id in changed_ids or callee.file is None or callee.kind not in CODE_KINDS:
                continue
            lo, hi = self._symbol_window(callee, [], cap=50)
            out.append(
                _Candidate(
                    TIER_CALLEE,
                    ContextBlock(
                        kind="callee",
                        file=callee.file,
                        symbol=callee.name,
                        line_start=lo,
                        line_end=hi,
                        code=self.snippet(callee.file, lo, hi),
                        reason=f"called by {node.name}",
                    ),
                )
            )
            if len(out) >= self.max_callees:
                break
        return out

    def _test_blocks(self, node: GraphNode) -> list[_Candidate]:
        out: list[_Candidate] = []
        for test in self.graph.tests_for(node.id)[: self.max_tests]:
            if test.file is None:
                continue
            lo, hi = self._symbol_window(test, [], cap=40)
            out.append(
                _Candidate(
                    TIER_TEST,
                    ContextBlock(
                        kind="test",
                        file=test.file,
                        symbol=test.name,
                        line_start=lo,
                        line_end=hi,
                        code=self.snippet(test.file, lo, hi),
                        reason=f"exercises {node.name}",
                    ),
                )
            )
        return out

    def _data_access(self, node: GraphNode) -> str:
        parts: list[str] = []
        for e in self.graph.out_edges(node.id, [EdgeKind.READS, EdgeKind.WRITES]):
            target = self.graph.node(e.target)
            if target is not None:
                parts.append(f"{e.kind.value} {target.name} (line {e.line})")
        if node.meta.get("db_in_loop"):
            parts.append(f"database access inside a loop at line(s) {node.meta['db_in_loop']}")
        return "; ".join(parts)

    def _import_block(self, change: FileChange) -> _Candidate | None:
        fs = self.symbols.get(change.path)
        if fs is None or not fs.imports:
            return None
        lines = sorted({i.line for i in fs.imports if i.line})
        if not lines:
            return None
        lo, hi = lines[0], min(lines[-1], lines[0] + 30)
        return _Candidate(
            TIER_IMPORT,
            ContextBlock(
                kind="import",
                file=change.path,
                line_start=lo,
                line_end=hi,
                code=self.snippet(change.path, lo, hi),
                reason="imports of changed file",
            ),
        )

    # ------------------------------------------------------------------ budgeting
    def _fit(self, candidates: list[_Candidate]) -> tuple[list[ContextBlock], bool, list[str]]:
        seen: list[tuple[str, int, int]] = []
        kept: list[_Candidate] = []
        dropped: list[str] = []
        used = 0
        truncated = False
        for cand in sorted(candidates, key=lambda c: c.tier):
            b = cand.block
            is_code = b.kind not in ("endpoint", "data")
            if is_code and any(
                f == b.file and s <= b.line_start and b.line_end <= e for f, s, e in seen
            ):
                continue  # already covered by a higher-priority block
            cost = len(b.code) + 80
            if used + cost > self.max_chars:
                truncated = True
                dropped.append(f"{b.kind}:{b.file}:{b.line_start}")
                continue
            used += cost
            if is_code:
                seen.append((b.file, b.line_start, b.line_end))
            kept.append(cand)
        return [c.block for c in kept], truncated, dropped

    # ------------------------------------------------------------------ UI graph
    def ui_subgraph(self, changed_ids: set[str]) -> CodeGraph:
        focus = {nid for nid in changed_ids if (n := self.graph.node(nid)) and n.kind in CODE_KINDS}
        keep: list[str] = list(focus)
        ring1 = self.graph.neighborhood(focus, depth=1) - focus
        for nid in changed_ids:
            path = self.graph.path_from_entrypoint(nid)
            for n in path or []:
                if n.id not in focus:
                    ring1.add(n.id)
        ring2 = self.graph.neighborhood(ring1 | focus, depth=1) - ring1 - focus
        for ring in (ring1, ring2):
            for nid in sorted(ring, key=lambda i: _rank(self.graph.node(i))):
                node = self.graph.node(nid)
                if node is None or node.kind is NodeKind.FILE:
                    continue
                if len(keep) >= self.max_graph_nodes:
                    break
                keep.append(nid)
        sub = self.graph.subgraph(keep)
        for nid in focus:
            n = sub.node(nid)
            if n is not None:
                n.meta["changed"] = "true"
        return sub


def _rank(node: GraphNode | None) -> int:
    if node is None:
        return 99
    order = {
        NodeKind.ENDPOINT: 0,
        NodeKind.DATABASE: 1,
        NodeKind.FUNCTION: 2,
        NodeKind.METHOD: 2,
        NodeKind.CLASS: 3,
        NodeKind.TEST: 4,
    }
    return order.get(node.kind, 9)


def _cluster(lines: list[int], gap: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in lines:
        if out and n - out[-1][1] <= gap:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out
