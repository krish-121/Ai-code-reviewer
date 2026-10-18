"""Confined repository file access for reviews and fixes.

Open each component relative to a pinned directory descriptor without following links.
This deliberately requires the documented POSIX/WSL runtime: a resolve-then-open fallback
on platforms without these primitives would reintroduce a symlink-swap vulnerability.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TextIO

from sentinel.core.domain.errors import SentinelError


class RepositoryPathError(SentinelError, ValueError):
    """A file cannot be accessed without escaping the repository boundary."""


@contextmanager
def repository_parent(root: Path, path: str) -> Iterator[tuple[int, str]]:
    """Pin an existing parent directory without following any symlink."""
    parts = relative_file(path).split("/")
    if os.open not in os.supports_dir_fd:
        raise RepositoryPathError("confined file access requires Linux/macOS or Windows WSL")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        for part in parts[:-1]:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        yield directory, parts[-1]


def create_repository_text(root: Path, path: str, text: str) -> None:
    """Create a new file exclusively in an existing confined directory."""
    with repository_parent(root, path) as (directory, name):
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)


def relative_file(path: str) -> str:
    """Validate a canonical, portable repository-relative file name."""
    parts = path.split("/")
    if (
        not path
        or "\\" in path
        or "\x00" in path
        or ":" in path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).drive
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RepositoryPathError("expected a canonical repository-relative file path")
    return path


@contextmanager
def repository_file(root: Path, path: str, *, write: bool = False) -> Iterator[TextIO]:
    """Open an existing regular, non-linked file; hold its identity through reads/writes."""
    parts = relative_file(path).split("/")
    if os.open not in os.supports_dir_fd:
        raise RepositoryPathError("confined file access requires Linux/macOS or Windows WSL")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        for part in parts[:-1]:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        mode = os.O_RDWR if write else os.O_RDONLY
        fd = os.open(parts[-1], mode | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stream = stack.enter_context(os.fdopen(fd, "r+" if write else "r", encoding="utf-8"))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RepositoryPathError("repository files must be regular files without hard links")
        yield stream


def read_repository_text(root: Path, path: str, limit: int | None = None) -> str:
    """Read through the confined accessor, optionally enforcing a character budget."""
    with repository_file(root, path) as stream:
        text = stream.read() if limit is None else stream.read(limit + 1)
    if limit is not None and len(text) > limit:
        raise RepositoryPathError("file exceeds the source size budget")
    return text


def write_repository_text(root: Path, path: str, text: str) -> None:
    """Replace contents through a pinned descriptor, never through a followed symlink."""
    with repository_file(root, path, write=True) as stream:
        stream.write(text)
        stream.truncate()
