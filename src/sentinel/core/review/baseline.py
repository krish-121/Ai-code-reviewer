"""Compare complete eligible base/head diagnostics for changes that remove code.

The orchestrator calls this instead of its changed-file-only static stage. Matching uses
unchanged source-line mappings, not line numbers or proximity to added lines. A missing
tool or snapshot never establishes that a diagnostic is new or pre-existing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from sentinel.analysis.graph.deletion import broken_imports
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.models import AnalysisRun, ChangeSet, ChangeType, Finding, ToolStatus
from sentinel.core.review.state import PipelineState
from sentinel.core.review.workspace import collect_sources

RunAnalysis = Callable[[Path, list[str]], tuple[list[Finding], list[AnalysisRun]]]
ExtractSymbols = Callable[[dict[str, str]], dict[str, FileSymbols]]


def needs_comparison(changeset: ChangeSet) -> bool:
    """Removals and renames can break references outside the changed files."""
    return any(
        f.deletions or f.change_type in (ChangeType.DELETED, ChangeType.RENAMED)
        for f in changeset.files
    )


def compare_diagnostics(
    before: list[Finding],
    after: list[Finding],
    base_sources: dict[str, str],
    head_sources: dict[str, str],
    changeset: ChangeSet,
    comparable: set[str],
) -> None:
    """Classify diagnostics by producer, rule, message and mapped unchanged source span.

    Only equal source blocks match: changing the text of a diagnostic's site keeps it
    eligible for review. Counters prevent a second identical occurrence being hidden.
    """
    renames = {f.path: f.old_path for f in changeset.files if f.old_path}
    available = Counter(_key(f, f.file, f.line_start, f.line_end) for f in before)
    mappings = _line_maps(base_sources, head_sources, renames)
    for finding in after:
        producers = {origin.split(":", 1)[0] for origin in finding.origins}
        if not producers or not producers <= comparable:
            finding.baseline_status = "unknown"
            continue
        mapping = mappings.get(finding.file, {})
        start, end = mapping.get(finding.line_start), mapping.get(finding.line_end)
        old_path = renames.get(finding.file) or finding.file
        key = _key(finding, old_path, start, end)
        unchanged = (
            start is not None
            and end is not None
            and all(
                mapping.get(line) == start + line - finding.line_start
                for line in range(finding.line_start, finding.line_end + 1)
            )
        )
        existing = unchanged and available[key] > 0
        finding.baseline_status = "pre-existing" if existing else "introduced"
        if existing:
            available[key] -= 1


def _key(finding: Finding, file: str, start: int | None, end: int | None) -> tuple[object, ...]:
    return (file, start, end, tuple(sorted(finding.origins)), finding.rule_id, finding.title)


def _line_maps(
    base: dict[str, str], head: dict[str, str], renames: dict[str, str]
) -> dict[str, dict[int, int]]:
    result: dict[str, dict[int, int]] = {}
    for path, source in head.items():
        old = base.get(renames.get(path) or path, "")
        matcher = SequenceMatcher(None, old.splitlines(), source.splitlines(), autojunk=True)
        result[path] = {
            block.b + offset + 1: block.a + offset + 1
            for block in matcher.get_matching_blocks()
            for offset in range(block.size)
        }
    return result


def analyze_deletions(
    state: PipelineState,
    run: RunAnalysis,
    extract: ExtractSymbols,
    config: RepoConfig,
    extensions: set[str],
    max_files: int,
) -> tuple[list[Finding], list[AnalysisRun]]:
    """Scan both eligible trees, including unchanged importers and transitive callers."""
    after, head_runs = run(state.workspace, sorted(state.sources))
    after = [f for f in after if f.file in state.sources]
    if state.baseline is None or not state.baseline.is_dir():
        incomplete(state, state.baseline_error or "base snapshot unavailable")
        for finding in after:
            finding.baseline_status = "unknown"
        return after, head_runs
    snapshot = collect_sources(
        state.baseline,
        extensions,
        [],
        max_files=max_files,
        ignore=[*config.ignore, *(f.path for f in state.changeset.skipped)],
        languages=config.languages,
    )
    if snapshot.truncated or snapshot.unreadable:
        incomplete(state, "base source inventory is truncated or unreadable")
    state.baseline_files = len(snapshot.sources)
    before, base_runs = run(state.baseline, sorted(snapshot.sources))
    comparable = _comparable_tools(state, base_runs, head_runs, bool(snapshot.sources))
    if snapshot.truncated or snapshot.unreadable:
        comparable.clear()
    compare_diagnostics(before, after, snapshot.sources, state.sources, state.changeset, comparable)
    symbols = extract(snapshot.sources)
    if any(fs.parse_error for fs in symbols.values()):
        incomplete(state, "base dependency parsing is incomplete")
    after.extend(broken_imports(symbols, state.file_symbols, state.changeset))
    records = [r.model_copy(update={"tool": f"base:{r.tool}"}) for r in base_runs]
    return after, [*head_runs, *records]


def _comparable_tools(
    state: PipelineState, base: list[AnalysisRun], head: list[AnalysisRun], has_base: bool
) -> set[str]:
    baseline = {r.tool: r.status for r in base}
    comparable = set()
    for record in head:
        old = baseline.get(record.tool, ToolStatus.OK if not has_base else None)
        if record.status == ToolStatus.OK and old == ToolStatus.OK:
            comparable.add(record.tool)
        else:
            incomplete(state, f"{record.tool}: base/head diagnostic comparison unavailable")
    if any(r.status != ToolStatus.OK for r in base):
        incomplete(state, "one or more base analyzers did not complete")
    if state.sources and not head:
        incomplete(state, "no head analyzer results")
    if has_base and not base:
        incomplete(state, "no base analyzer results")
    return comparable


def incomplete(state: PipelineState, detail: str) -> None:
    """Persist a visible limitation and keep the review partial."""
    message = f"Deletion impact incomplete: {detail}"
    if message not in state.result.errors:
        state.result.errors.append(message)
        state.limitations.append(message)
