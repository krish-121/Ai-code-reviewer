"""Find imports that resolved to local modules before a change but no longer do.

This supplements compiler diagnostics (mypy deliberately ignores missing third-party
imports). Only previously resolved local dependencies qualify; external packages and
dynamic loading are not guessed. All surviving source files are inspected.
"""

from __future__ import annotations

from sentinel.analysis.graph.builder import GraphBuilder
from sentinel.analysis.graph.resolution import SymbolTable, resolve_imports
from sentinel.analysis.static.base import static_finding
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.models import Category, ChangeSet, ChangeType, Finding, Severity


def broken_imports(
    before: dict[str, FileSymbols], after: dict[str, FileSymbols], changeset: ChangeSet
) -> list[Finding]:
    """Report surviving import sites whose previously local module disappeared."""
    base, head = GraphBuilder(before), GraphBuilder(after)
    base.build()
    head.build()
    renames = {f.path: f.old_path for f in changeset.files if f.old_path}
    removed = {f.path for f in changeset.files if f.change_type is ChangeType.DELETED}
    removed.update(renames.values())
    findings = []
    for path, symbols in after.items():
        old = before.get(renames.get(path) or path, symbols)
        if old.parse_error or symbols.parse_error:
            continue
        findings.extend(_missing_imports(base.table, head.table, old, symbols, removed))
    return findings


def _missing_imports(
    base: SymbolTable, head: SymbolTable, old: FileSymbols, current: FileSymbols, removed: set[str]
) -> list[Finding]:
    findings = []
    for imp in current.imports:
        _, old_targets = resolve_imports(base, old.model_copy(update={"imports": [imp]}))
        _, new_targets = resolve_imports(head, current.model_copy(update={"imports": [imp]}))
        missing = {p for p, _ in old_targets if p in removed and p not in head.files}
        if not missing or new_targets:
            continue
        finding = static_finding(
            tool="sentinel-deletion",
            rule="removed-local-import",
            category=Category.BUG,
            severity=Severity.HIGH,
            confidence=0.9,
            file=current.path,
            line=imp.line,
            title=f"Import lost its local dependency: {imp.module or '(relative module)'}",
            explanation="This import resolved in the base tree, but its local target is absent "
            "in the head tree: " + ", ".join(sorted(missing)),
            tags=["deletion-impact"],
        )
        finding.baseline_status = "introduced"
        findings.append(finding)
    return findings
