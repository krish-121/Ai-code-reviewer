"""Collect the repository files the code graph is built from."""

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

MAX_FILE_BYTES = 400_000


@dataclass
class RepoSnapshot:
    sources: dict[str, str]
    truncated: bool = False
    skipped: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(len(s) for s in self.sources.values())


def _eligible(path: str) -> bool:
    low = path.lower()
    if any(low.startswith(d) or f"/{d}" in low for d in GENERATED_DIRS):
        return False
    if low.endswith((*GENERATED_SUFFIXES, ".d.ts")):
        return False
    return sensitive_file_reason(path) is None


def collect_sources(
    workspace: Path,
    supports: set[str] | None,
    priority_paths: list[str],
    *,
    max_files: int = 2_000,
    max_bytes: int = 25_000_000,
) -> RepoSnapshot:
    """Read code files, changed files first, then their directories, then the rest.

    ``supports`` is the set of file extensions a language analyzer exists for.
    """
    try:
        all_files = list_files(workspace)
    except (GitError, OSError):
        all_files = []
    exts = supports or set()
    candidates = [p for p in all_files if posixpath.splitext(p)[1].lower() in exts and _eligible(p)]
    changed = [
        p
        for p in dict.fromkeys(priority_paths)
        if posixpath.splitext(p)[1].lower() in exts and (workspace / p).is_file()
    ]
    changed_set = set(changed)
    changed_dirs = {posixpath.dirname(p) for p in changed}
    rest = sorted(
        (p for p in candidates if p not in changed_set),
        key=lambda p: (posixpath.dirname(p) not in changed_dirs, p.count("/"), p),
    )
    snapshot = RepoSnapshot(sources={})
    total = 0
    for path in [*changed, *rest]:
        if len(snapshot.sources) >= max_files or total >= max_bytes:
            snapshot.truncated = True
            break
        full = workspace / path
        try:
            if full.stat().st_size > MAX_FILE_BYTES:
                snapshot.skipped.append(path)
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            snapshot.skipped.append(path)
            continue
        snapshot.sources[path] = text
        total += len(text)
    return snapshot
