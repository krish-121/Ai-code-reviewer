"""Apply a reviewed multi-file proposal through confined descriptors with rollback.

All existing-file hashes and absent-file expectations are checked before writes. Ordinary
write failures restore prior contents and remove only files created by this operation.
This is not a filesystem transaction against process termination or power loss.
"""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from sentinel.core.domain.errors import SentinelError
from sentinel.core.fixes.outcome import FixOutcome
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256
from sentinel.core.fixes.safety import check_fix_path
from sentinel.core.paths import RepositoryPathError, repository_file, repository_parent


class ApplyError(SentinelError):
    """A proposal cannot be applied safely or requires recovery after a write failure."""


def apply_fix(repo_root: Path, outcome: FixOutcome) -> list[str]:
    """Preflight the whole proposal, then write it with rollback on ordinary failures."""
    if not outcome.ok:
        raise ApplyError(f"refusing to apply a fix with status {outcome.status}")
    try:
        with ExitStack() as stack:
            files, streams, absent = _preflight(repo_root, outcome, stack)
            after = apply_edits(files, outcome.edits, allowed_new_files=absent)
            _commit(after, files, streams, absent, stack)
            return sorted(after)
    except (OSError, UnicodeError, RepositoryPathError, PatchError) as exc:
        raise ApplyError(str(exc)) from exc


def _preflight(
    root: Path, outcome: FixOutcome, stack: ExitStack
) -> tuple[dict[str, str], dict[str, TextIO], dict[str, tuple[int, str]]]:
    files: dict[str, str] = {}
    streams: dict[str, TextIO] = {}
    absent: dict[str, tuple[int, str]] = {}
    edited = {edit.file for edit in outcome.edits}
    for path, digest in outcome.original_hashes.items():
        check_fix_path(path)
        if digest is None:
            parent = stack.enter_context(repository_parent(root, path))
            _require_absent(*parent)
            absent[path] = parent
        else:
            stream = stack.enter_context(repository_file(root, path, write=path in edited))
            current = stream.read()
            if sha256(current) != digest:
                raise ApplyError(f"{path} changed since the fix was generated; regenerate the fix")
            streams[path], files[path] = stream, current
    return files, streams, absent


def _require_absent(directory: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ApplyError(f"new file {name} already exists; regenerate the fix")


def _replace_text(stream: TextIO, content: str) -> None:
    stream.seek(0)
    stream.write(content)
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def _commit(
    after: dict[str, str],
    before: dict[str, str],
    streams: dict[str, TextIO],
    absent: dict[str, tuple[int, str]],
    stack: ExitStack,
) -> None:
    attempted: list[str] = []
    created: dict[str, os.stat_result] = {}
    try:
        for path, content in after.items():
            if path in absent:
                directory, name = absent[path]
                fd = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                streams[path] = stack.enter_context(os.fdopen(fd, "w+", encoding="utf-8"))
                created[path] = os.fstat(fd)
            attempted.append(path)
            _replace_text(streams[path], content)
    except BaseException as exc:
        failures = _rollback(attempted, created, before, streams, absent)
        if failures:
            raise ApplyError(
                "write failed and rollback was incomplete; recover these files "
                "from your backup: " + ", ".join(failures)
            ) from exc
        raise


def _rollback(
    attempted: list[str],
    created: dict[str, os.stat_result],
    before: dict[str, str],
    streams: dict[str, TextIO],
    absent: dict[str, tuple[int, str]],
) -> list[str]:
    failures = []
    for path in reversed(attempted):
        try:
            if path in created:
                directory, name = absent[path]
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                original = created[path]
                if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                    raise ApplyError("created file was replaced during rollback")
                os.unlink(name, dir_fd=directory)
            else:
                _replace_text(streams[path], before[path])
        except (OSError, ApplyError):
            failures.append(path)
    return failures
