"""Throwaway copies of a repository for patch validation."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

SYMLINK_DIRS = {"node_modules", ".venv", "venv"}
COPY_IGNORE = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    "coverage",
    ".tox",
}


def scratch_copy(root: Path, prefix: str = "sentinel-sbx-") -> Path:
    """Copy a repository into a temporary directory (dependencies are symlinked)."""
    dest = Path(tempfile.mkdtemp(prefix=prefix))
    for entry in root.iterdir():
        if entry.name in COPY_IGNORE:
            continue
        target = dest / entry.name
        if entry.name in SYMLINK_DIRS and entry.is_dir():
            target.symlink_to(entry.resolve(), target_is_directory=True)
        elif entry.is_dir() and not entry.is_symlink():
            shutil.copytree(
                entry,
                target,
                symlinks=True,
                ignore=shutil.ignore_patterns(*COPY_IGNORE),
            )
        elif entry.is_file():
            shutil.copy2(entry, target)
    return dest
