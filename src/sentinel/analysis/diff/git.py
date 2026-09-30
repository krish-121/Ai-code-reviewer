"""Obtain change sets from a local git repository or a plain directory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sentinel.analysis.diff.parser import (
    UnsafePathError,
    detect_language,
    parse_unified_diff,
    whole_file_change,
)
from sentinel.core.domain.models import ChangeSet, Language, SkippedFile

DIFF_ARGS = ["diff", "-M", "--no-color", "--no-ext-diff", "--unified=3"]
WALK_EXCLUDE = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".next",
    "coverage",
}
MAX_WHOLE_FILE_BYTES = 400_000


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def is_git_repo(path: Path) -> bool:
    try:
        _git(path, "rev-parse", "--is-inside-work-tree")
    except GitError:
        return False
    return True


def repo_root(path: Path) -> Path:
    if path.is_file():
        path = path.parent
    if is_git_repo(path):
        return Path(_git(path, "rev-parse", "--show-toplevel").strip())
    return path.resolve()


def head_sha(repo: Path) -> str | None:
    try:
        return _git(repo, "rev-parse", "HEAD").strip()
    except GitError:
        return None


def staged_changeset(repo: Path) -> ChangeSet:
    cs = parse_unified_diff(_git(repo, *DIFF_ARGS, "--cached"), source="staged")
    cs.head_ref = "INDEX"
    cs.base_ref = head_sha(repo)
    cs.title = "Staged changes"
    return cs


def worktree_changeset(repo: Path) -> ChangeSet:
    cs = parse_unified_diff(_git(repo, *DIFF_ARGS, "HEAD"), source="worktree")
    cs.base_ref = head_sha(repo)
    cs.head_ref = "WORKTREE"
    cs.title = "Uncommitted changes"
    return cs


def range_changeset(repo: Path, base: str, head: str) -> ChangeSet:
    for ref in (base, head):
        if ref.startswith("-"):
            raise GitError(f"invalid ref {ref!r}")
    cs = parse_unified_diff(_git(repo, *DIFF_ARGS, f"{base}...{head}"), source="range")
    cs.base_ref, cs.head_ref = base, head
    cs.title = f"{base}...{head}"
    return cs


def list_files(root: Path, sub: Path | None = None) -> list[str]:
    """Repository-relative paths of tracked (or, outside git, all non-hidden) files."""
    target = (sub or root).resolve()
    if not target.is_relative_to(root.resolve()):
        raise UnsafePathError(f"{target} is outside the repository")
    if is_git_repo(root):
        rel = os.path.relpath(target, root)
        out = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", rel)
        return sorted(p for p in out.splitlines() if p)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in WALK_EXCLUDE and not d.startswith(".")]
        for name in filenames:
            full = Path(dirpath) / name
            found.append(full.relative_to(root).as_posix())
    return sorted(found)


def path_changeset(root: Path, sub: Path | None = None) -> ChangeSet:
    """Treat every file under ``sub`` as newly added: review existing code as-is."""
    cs = ChangeSet(source="path", title=f"Review of {(sub or root).name or root}")
    for rel in list_files(root, sub):
        full = root / rel
        # Non-code files are only kept when they may hold config/secrets worth scanning.
        if (
            detect_language(rel) is Language.OTHER
            and not rel.split("/")[-1].startswith(".env")
            and full.suffix not in {".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ""}
        ):
            continue
        try:
            if full.stat().st_size > MAX_WHOLE_FILE_BYTES:
                cs.skipped.append(SkippedFile(path=rel, reason="too large"))
                continue
            data = full.read_bytes()
        except OSError as exc:
            cs.skipped.append(SkippedFile(path=rel, reason=f"unreadable: {exc}"))
            continue
        if b"\x00" in data[:8192]:
            cs.skipped.append(SkippedFile(path=rel, reason="binary file"))
            continue
        cs.files.append(whole_file_change(rel, data.decode("utf-8", errors="replace")))
    return cs
