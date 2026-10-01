"""Reading repository files for a review, and keeping a redacted copy for the UI.

``collect_sources`` runs in the orchestrator's build-graph stage: it reads the code files
the code graph is built from, changed files first. ``snapshot_sources`` runs in the
finalize stage: it keeps redacted copies of the files the web UI may need to display, so
the UI never reads the repository directly.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.analysis.diff.filtering import (
    GENERATED_DIRS,
    GENERATED_SUFFIXES,
    sensitive_file_reason,
)
from sentinel.analysis.diff.git import GitError, list_files
from sentinel.analysis.diff.secrets import redact_text
from sentinel.analysis.graph.context import ContextBundle
from sentinel.core.domain.models import ChangeSet, Finding

MAX_FILE_BYTES = 400_000
DEFAULT_MAX_FILES = 2_000
DEFAULT_MAX_BYTES = 25_000_000
MAX_SNAPSHOT_BYTES = 3_000_000
TYPE_DECLARATION_SUFFIX = ".d.ts"


@dataclass
class RepoSnapshot:
    """Source files read from the repository (path -> text)."""

    sources: dict[str, str]
    truncated: bool = False
    skipped: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        """Characters read in total."""
        return sum(len(s) for s in self.sources.values())


def collect_sources(
    workspace: Path,
    supports: set[str] | None,
    priority_paths: list[str],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> RepoSnapshot:
    """Read code files: changed files first, then their directories, then the rest.

    Args:
        workspace: Repository root.
        supports: File extensions a language analyzer exists for.
        priority_paths: Changed files; always read first so a size limit never drops them.
        max_files: Stop after this many files (the snapshot is then marked truncated).
        max_bytes: Stop after this many characters.
    """
    snapshot = RepoSnapshot(sources={})
    total = 0
    for path in _paths_in_reading_order(workspace, supports or set(), priority_paths):
        if len(snapshot.sources) >= max_files or total >= max_bytes:
            snapshot.truncated = True
            break
        text = _read_small_file(workspace / path)
        if text is None:
            snapshot.skipped.append(path)
            continue
        snapshot.sources[path] = text
        total += len(text)
    return snapshot


def snapshot_sources(
    changeset: ChangeSet,
    sources: dict[str, str],
    bundle: ContextBundle | None,
    findings: list[Finding],
) -> dict[str, str]:
    """Redacted copies of the files the UI may need to show (diff, findings, context, graph)."""
    wanted: list[str] = [f.path for f in changeset.reviewable()]
    wanted += [f.file for f in findings]
    if bundle is not None:
        wanted += [b.file for b in bundle.blocks]
        wanted += [n.file for n in bundle.subgraph.nodes if n.file]
    snapshot: dict[str, str] = {}
    total = 0
    for path in dict.fromkeys(wanted):  # de-duplicate, keep order
        text = sources.get(path)
        if text is None or total + len(text) > MAX_SNAPSHOT_BYTES:
            continue
        redacted, _ = redact_text(text)
        snapshot[path] = redacted
        total += len(redacted)
    return snapshot


def _paths_in_reading_order(
    workspace: Path, extensions: set[str], priority_paths: list[str]
) -> list[str]:
    """Changed files, then files in the same directories, then everything else (shallow first)."""
    try:
        all_files = list_files(workspace)
    except (GitError, OSError):
        all_files = []
    changed = [
        p
        for p in dict.fromkeys(priority_paths)
        if _extension(p) in extensions and (workspace / p).is_file()
    ]
    changed_set = set(changed)
    changed_dirs = {posixpath.dirname(p) for p in changed}
    rest = [
        p
        for p in all_files
        if p not in changed_set and _extension(p) in extensions and _is_eligible(p)
    ]
    rest.sort(key=lambda p: (posixpath.dirname(p) not in changed_dirs, p.count("/"), p))
    return [*changed, *rest]


def _read_small_file(path: Path) -> str | None:
    """File text, or None when the file is too large or unreadable."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _extension(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def _is_eligible(path: str) -> bool:
    """False for generated, vendored, declaration and sensitive files."""
    low = path.lower()
    if any(low.startswith(d) or f"/{d}" in low for d in GENERATED_DIRS):
        return False
    if low.endswith((*GENERATED_SUFFIXES, TYPE_DECLARATION_SUFFIX)):
        return False
    return sensitive_file_reason(path) is None
