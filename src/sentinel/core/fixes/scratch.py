"""Throwaway copies of a repository for patch validation."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from sentinel.analysis.diff.filtering import sensitive_file_reason
from sentinel.core.paths import repository_file

COPY_IGNORE = {
    "node_modules",
    ".venv",
    "venv",
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
    """Copy regular files through confined descriptors; dependencies belong in the image."""
    dest = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        for directory, dirs, files in os.walk(root, followlinks=False):
            folder = Path(directory)
            dirs[:] = [d for d in dirs if d not in COPY_IGNORE and not (folder / d).is_symlink()]
            relative = folder.relative_to(root)
            (dest / relative).mkdir(parents=True, exist_ok=True)
            for name in files:
                if name in COPY_IGNORE or (folder / name).is_symlink():
                    continue
                path = (relative / name).as_posix()
                if sensitive_file_reason(path):
                    continue
                with repository_file(root, path) as source:
                    target = dest / path
                    target.write_bytes(source.buffer.read())
                    target.chmod(os.fstat(source.fileno()).st_mode & 0o777)
        return dest
    except Exception:
        shutil.rmtree(dest)
        raise
