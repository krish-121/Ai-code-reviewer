"""Context engine: pick the surrounding code the reviewer (human or AI) needs.

For every changed function/class it gathers the full changed body, its callers (around
the call site), its callees, tests that exercise it, the path from the nearest entry
point, and the data stores it touches — then fits that into a character budget by
priority. It never sends the whole repository.

Called by the orchestrator's extract-context stage; the resulting blocks go into the AI
prompt (``core/review/ai_request.py``). Blocks are redacted again here, as a second line
of defence after the filter stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.analysis.diff.secrets import redact_text
from sentinel.analysis.graph.architecture import DEFAULT_MAX_NODES, architecture_subgraph
from sentinel.analysis.graph.import_context import imported_data_nodes
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

# Priority tiers: when the budget runs out, higher tiers are dropped first.
TIER_CHANGED, TIER_CALLER, TIER_CALLEE, TIER_TEST, TIER_PATH, TIER_IMPORT = range(6)

DEFAULT_MAX_CHARS = 60_000
CHANGED_WINDOW_LINES = 160  # longest slice of a changed symbol to include
CALLEE_WINDOW_LINES = 50
TEST_WINDOW_LINES = 40
CALLER_LINES_BEFORE, CALLER_LINES_AFTER = 10, 8  # around the call site
MODULE_CHANGE_GAP = 6  # module-level changed lines closer than this form one block
MODULE_CHANGE_MARGIN = 3
MAX_IMPORT_BLOCK_LINES = 30
BLOCK_OVERHEAD_CHARS = 80  # prompt framing around each block
NOTE_KINDS = frozenset({"endpoint", "data"})  # blocks that are notes, not source code
COMMENT_PREFIXES = ("#", "//")
FILE_NODE_NAME = "<file>"


@dataclass
class ChangedSymbol:
    """A function, class or file (for module-level edits) touched by the diff."""

    node_id: str
    file: str
    name: str
    kind: NodeKind
    changed_lines: list[int]


@dataclass
class ContextBundle:
    """Everything the context engine produced for one review."""

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
    """A block that may go into the prompt, with its priority tier."""

    tier: int
    block: ContextBlock


class ContextEngine:
    """Chooses and budgets the code context for a change."""

    def __init__(
        self,
        graph: CodeGraph,
        sources: dict[str, str],
        symbols: dict[str, FileSymbols] | None = None,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        max_callers: int = 4,
        max_callees: int = 6,
        max_tests: int = 3,
        max_graph_nodes: int = DEFAULT_MAX_NODES,
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
        """Lines ``start..end`` of a file, each prefixed with its line number."""
        lines = self._lines(path)
        start = max(1, start)
        end = min(len(lines), end)
        width = len(str(end))
        return "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1))

    def _symbol_window(self, node: GraphNode, focus: list[int], cap: int) -> tuple[int, int]:
        """The symbol's lines, or a ``cap``-line slice of them centred near ``focus``."""
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
        """The symbols whose code the diff changes (blank and comment lines ignored)."""
        found: dict[str, ChangedSymbol] = {}
        for change in changeset.reviewable():
            for line in _meaningful_added_lines(change):
                node = self.graph.enclosing(change.path, line) or self.graph.node(
                    node_id(NodeKind.FILE, change.path, FILE_NODE_NAME)
                )
                if node is not None:
                    _remember(found, node, change.path).changed_lines.append(line)
            # Removed-only hunks still change behaviour of the enclosing symbol.
            for hunk in change.hunks:
                if hunk.new_count and not any(ln.kind is LineKind.ADDED for ln in hunk.lines):
                    node = self.graph.enclosing(change.path, hunk.new_start)
                    if node is not None:
                        _remember(found, node, change.path)
        return list(found.values())

    # ------------------------------------------------------------------ build
    def build(self, changeset: ChangeSet) -> ContextBundle:
        """Collect candidate blocks for every changed symbol and fit them into the budget."""
        changed = self.changed_symbols(changeset)
        changed_ids = {c.node_id for c in changed}
        candidates: list[_Candidate] = []
        call_paths: dict[str, list[str]] = {}
        for symbol in changed:
            candidates += self._candidates_for(symbol, changeset, changed_ids, call_paths)
        for change in changeset.reviewable():
            import_block = self._import_block(change)
            if import_block is not None:
                candidates.append(import_block)
            for definition in imported_data_nodes(
                self.graph, self.symbols, change.path, limit=self.max_callees
            ):
                if definition.id not in changed_ids and definition.file in self.sources:
                    lo, hi = self._symbol_window(definition, [], cap=CALLEE_WINDOW_LINES)
                    candidates.append(
                        self._code_block(
                            TIER_CALLEE,
                            "dependency",
                            definition,
                            lo,
                            hi,
                            f"named data import of {change.path}",
                        )
                    )
        blocks, truncated, dropped = self._fit(candidates)
        redactions = _redact(blocks)
        return ContextBundle(
            blocks=blocks,
            changed_symbols=changed,
            call_paths=call_paths,
            stats=_stats(blocks, changed),
            truncated=truncated,
            subgraph=architecture_subgraph(self.graph, changed_ids, self.max_graph_nodes),
            redactions=redactions,
            dropped=dropped,
        )

    def _candidates_for(
        self,
        symbol: ChangedSymbol,
        changeset: ChangeSet,
        changed_ids: set[str],
        call_paths: dict[str, list[str]],
    ) -> list[_Candidate]:
        """The changed code itself plus its callers, callees, tests, entry path and data."""
        node = self.graph.node(symbol.node_id)
        if node is None:
            return []
        if node.kind is NodeKind.FILE:
            change = changeset.get(symbol.file)
            return self._module_level_blocks(change, symbol.changed_lines) if change else []
        lo, hi = self._symbol_window(node, symbol.changed_lines, cap=CHANGED_WINDOW_LINES)
        candidates = [
            self._code_block(TIER_CHANGED, "changed", node, lo, hi, "changed in this diff"),
            *self._caller_blocks(node, changed_ids),
            *self._callee_blocks(node, changed_ids),
            *self._test_blocks(node),
            *self._variable_blocks(node, changed_ids),
        ]
        path = self.graph.path_from_entrypoint(node.id)
        if path and len(path) > 1:
            call_paths[node.id] = [_label(n) for n in path]
            route = "Reachable via: " + " -> ".join(call_paths[node.id])
            candidates.append(self._note_block("endpoint", node, route, "nearest entry point"))
        data = self._data_access(node)
        if data:
            candidates.append(
                self._note_block("data", node, data, "variables and data stores touched")
            )
        return candidates

    def _code_block(
        self, tier: int, kind: str, node: GraphNode, lo: int, hi: int, reason: str
    ) -> _Candidate:
        """A block with the source lines ``lo..hi`` of ``node``'s file."""
        file = node.file or ""
        return _Candidate(
            tier,
            ContextBlock(
                kind=kind,
                file=file,
                symbol=node.name,
                line_start=lo,
                line_end=hi,
                code=self.snippet(file, lo, hi),
                reason=reason,
            ),
        )

    @staticmethod
    def _note_block(kind: str, node: GraphNode, text: str, reason: str) -> _Candidate:
        """A one-line note about ``node`` (entry path, data access) rather than code."""
        line = node.line_start or 1
        return _Candidate(
            TIER_PATH,
            ContextBlock(
                kind=kind,
                file=node.file or "",
                symbol=node.name,
                line_start=line,
                line_end=line,
                code=text,
                reason=reason,
            ),
        )

    def _module_level_blocks(self, change: FileChange, lines: list[int]) -> list[_Candidate]:
        out: list[_Candidate] = []
        for lo, hi in _cluster(sorted(lines), gap=MODULE_CHANGE_GAP):
            s, e = max(1, lo - MODULE_CHANGE_MARGIN), hi + MODULE_CHANGE_MARGIN
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

    def _variable_blocks(self, node: GraphNode, changed_ids: set[str]) -> list[_Candidate]:
        """Include variable definitions, or the consumers of a changed variable."""
        out: list[_Candidate] = []
        accesses = (EdgeKind.READS, EdgeKind.WRITES)
        edges = (
            self.graph.in_edges(node.id, accesses)
            if node.kind is NodeKind.VARIABLE
            else self.graph.out_edges(node.id, accesses)
        )
        for edge in edges:
            other_id = edge.source if node.kind is NodeKind.VARIABLE else edge.target
            other = self.graph.node(other_id)
            if other is None or other.id in changed_ids or other.file is None:
                continue
            if node.kind is not NodeKind.VARIABLE and other.kind is not NodeKind.VARIABLE:
                continue
            lo, hi = self._symbol_window(other, [edge.line or 1], cap=CALLEE_WINDOW_LINES)
            reason = (
                f"{edge.kind.value} {node.name}"
                if node.kind is NodeKind.VARIABLE
                else (f"{node.name} {edge.kind.value} this variable")
            )
            out.append(self._code_block(TIER_CALLEE, "dependency", other, lo, hi, reason))
            if len(out) >= self.max_callees:
                break
        return out

    def _caller_blocks(self, node: GraphNode, changed_ids: set[str]) -> list[_Candidate]:
        """The lines around each production call site of ``node`` (tests have their own tier)."""
        out: list[_Candidate] = []
        for edge in self.graph.in_edges(node.id, [EdgeKind.CALLS]):
            caller = self.graph.node(edge.source)
            if caller is None or caller.id in changed_ids or caller.kind is NodeKind.TEST:
                continue
            if caller.file is None or edge.line is None:
                continue
            lo = max(caller.line_start or 1, edge.line - CALLER_LINES_BEFORE)
            hi = min(caller.line_end or edge.line, edge.line + CALLER_LINES_AFTER)
            reason = f"calls {node.name} at line {edge.line}"
            out.append(self._code_block(TIER_CALLER, "caller", caller, lo, hi, reason))
            if len(out) >= self.max_callers:
                break
        return out

    def _callee_blocks(self, node: GraphNode, changed_ids: set[str]) -> list[_Candidate]:
        """The start of each function ``node`` calls."""
        out: list[_Candidate] = []
        for callee in self.graph.callees(node.id):
            if callee.id in changed_ids or callee.file is None or callee.kind not in CODE_KINDS:
                continue
            lo, hi = self._symbol_window(callee, [], cap=CALLEE_WINDOW_LINES)
            reason = f"called by {node.name}"
            out.append(self._code_block(TIER_CALLEE, "callee", callee, lo, hi, reason))
            if len(out) >= self.max_callees:
                break
        return out

    def _test_blocks(self, node: GraphNode) -> list[_Candidate]:
        """Tests that exercise ``node`` directly or through a short call chain."""
        out: list[_Candidate] = []
        for test in self.graph.tests_for(node.id)[: self.max_tests]:
            if test.file is None:
                continue
            lo, hi = self._symbol_window(test, [], cap=TEST_WINDOW_LINES)
            out.append(self._code_block(TIER_TEST, "test", test, lo, hi, f"exercises {node.name}"))
        return out

    def _data_access(self, node: GraphNode) -> str:
        """One line describing the tables ``node`` reads or writes, and queries in loops."""
        parts: list[str] = []
        for e in self.graph.out_edges(node.id, [EdgeKind.READS, EdgeKind.WRITES]):
            target = self.graph.node(e.target)
            if target is not None:
                parts.append(f"{e.kind.value} {target.name} (line {e.line})")
        if node.meta.get("db_in_loop"):
            parts.append(f"database access inside a loop at line(s) {node.meta['db_in_loop']}")
        return "; ".join(parts)

    def _import_block(self, change: FileChange) -> _Candidate | None:
        """The import section of a changed file."""
        fs = self.symbols.get(change.path)
        if fs is None or not fs.imports:
            return None
        lines = sorted({i.line for i in fs.imports if i.line})
        if not lines:
            return None
        lo, hi = lines[0], min(lines[-1], lines[0] + MAX_IMPORT_BLOCK_LINES)
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
        """Keep blocks in tier order until ``max_chars`` is used; skip already-covered code.

        Returns the kept blocks, whether anything was dropped, and what was dropped.
        """
        covered: list[tuple[str, int, int]] = []
        kept: list[ContextBlock] = []
        dropped: list[str] = []
        used = 0
        for candidate in sorted(candidates, key=lambda c: c.tier):
            block = candidate.block
            is_code = block.kind not in NOTE_KINDS
            if is_code and _is_covered(block, covered):
                continue
            cost = len(block.code) + BLOCK_OVERHEAD_CHARS
            if used + cost > self.max_chars:
                dropped.append(f"{block.kind}:{block.file}:{block.line_start}")
                continue
            used += cost
            if is_code:
                covered.append((block.file, block.line_start, block.line_end))
            kept.append(block)
        return kept, bool(dropped), dropped


def _meaningful_added_lines(change: FileChange) -> list[int]:
    """Added lines that hold code (not blank, not a comment), in order."""
    return sorted(
        {
            ln.new_lineno
            for h in change.hunks
            for ln in h.lines
            if ln.kind is LineKind.ADDED
            and ln.new_lineno is not None
            and ln.content.strip()
            and not ln.content.strip().startswith(COMMENT_PREFIXES)
        }
    )


def _remember(found: dict[str, ChangedSymbol], node: GraphNode, path: str) -> ChangedSymbol:
    """The ChangedSymbol for ``node``, created on first sight."""
    return found.setdefault(node.id, ChangedSymbol(node.id, path, node.name, node.kind, []))


def _label(node: GraphNode) -> str:
    """How a node is written in a call path: ``search()``, ``GET /search``, ``User``."""
    if node.kind in (NodeKind.ENDPOINT, NodeKind.DATABASE, NodeKind.CLASS, NodeKind.VARIABLE):
        return node.name
    return f"{node.name}()"


def _is_covered(block: ContextBlock, covered: list[tuple[str, int, int]]) -> bool:
    """True when a kept block already contains all of ``block``'s lines."""
    return any(
        file == block.file and start <= block.line_start and block.line_end <= end
        for file, start, end in covered
    )


def _redact(blocks: list[ContextBlock]) -> int:
    """Redact secrets in place; return how many were found."""
    total = 0
    for block in blocks:
        block.code, count = redact_text(block.code)
        total += count
    return total


def _stats(blocks: list[ContextBlock], changed: list[ChangedSymbol]) -> dict[str, int]:
    """Block counts per kind, total characters and number of changed symbols."""
    stats: dict[str, int] = {}
    for block in blocks:
        stats[block.kind] = stats.get(block.kind, 0) + 1
    stats["chars"] = sum(len(b.code) for b in blocks)
    stats["changed_symbols"] = len(changed)
    return stats


def _cluster(lines: list[int], gap: int) -> list[tuple[int, int]]:
    """Group sorted line numbers into ranges, joining lines at most ``gap`` apart."""
    out: list[tuple[int, int]] = []
    for n in lines:
        if out and n - out[-1][1] <= gap:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out
