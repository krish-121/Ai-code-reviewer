"""Bounded scratch transfer for workers whose paths do not exist on the Docker host.

The worker packs only confined regular files. The installed sandbox launcher unpacks
them into an empty tmpfs before executing a command; no generated files return to the
worker. Neither side follows archive links or extracts privileged file metadata.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path
from typing import BinaryIO

from sentinel.analysis.diff.filtering import sensitive_file_reason
from sentinel.core.domain.errors import SentinelError
from sentinel.core.fixes.scratch import COPY_IGNORE
from sentinel.core.paths import relative_file, repository_file, repository_parent

MAX_WORKSPACE_BYTES = 128 * 1024**2
MAX_WORKSPACE_FILES = 10_000  # Files and directories both consume the entry budget.


class SandboxWorkspaceError(SentinelError, ValueError):
    """Scratch data cannot be transferred within the sandbox's safety limits."""


def pack_workspace(root: Path, output: BinaryIO) -> None:
    """Write a bounded tar of regular, non-sensitive files without following links."""
    total, count = 0, 0
    with tarfile.open(fileobj=output, mode="w|") as archive:
        for directory, dirs, files in os.walk(root, followlinks=False):
            folder = Path(directory)
            dirs[:] = [d for d in dirs if d not in COPY_IGNORE and not (folder / d).is_symlink()]
            if folder != root:
                count += 1
                _check_budget(total, count)
                member = tarfile.TarInfo(relative_file(folder.relative_to(root).as_posix()))
                member.type, member.mode = tarfile.DIRTYPE, 0o700
                archive.addfile(member)
            for name in sorted(files):
                path = (folder / name).relative_to(root).as_posix()
                if name in COPY_IGNORE or sensitive_file_reason(path):
                    continue
                with repository_file(root, path) as source:
                    info = os.fstat(source.fileno())
                    total, count = total + info.st_size, count + 1
                    _check_budget(total, count)
                    member = tarfile.TarInfo(relative_file(path))
                    member.size = info.st_size
                    member.mode = 0o700 if info.st_mode & 0o111 else 0o600
                    archive.addfile(member, source.buffer)
    if output.tell() > MAX_WORKSPACE_BYTES + MAX_WORKSPACE_FILES * 2048:
        raise SandboxWorkspaceError("scratch archive exceeds transfer budget")


def unpack_workspace(stream: BinaryIO, root: Path) -> None:
    """Extract regular files exclusively into the empty container tmpfs."""
    total, count = 0, 0
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            path = relative_file(member.name.rstrip("/"))
            total, count = total + member.size, count + 1
            _check_budget(total, count)
            if member.isdir():
                (root / path).mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            if not member.isfile() or member.size < 0:
                raise SandboxWorkspaceError("scratch archive must contain only regular files")
            _unpack_file(archive, member, root, path)


def _unpack_file(archive: tarfile.TarFile, member: tarfile.TarInfo, root: Path, path: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = archive.extractfile(member)
    if source is None:
        raise SandboxWorkspaceError("scratch archive file is missing")
    with source, repository_parent(root, path) as (directory, name):
        mode = 0o700 if member.mode & 0o111 else 0o600
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory
        )
        with os.fdopen(fd, "wb") as target:
            shutil.copyfileobj(source, target, length=64 * 1024)


def _check_budget(total: int, count: int) -> None:
    if total > MAX_WORKSPACE_BYTES or count > MAX_WORKSPACE_FILES:
        raise SandboxWorkspaceError("scratch workspace exceeds byte or file budget")
