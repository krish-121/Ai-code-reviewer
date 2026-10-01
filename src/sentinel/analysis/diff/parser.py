"""Unified-diff parser.

Turns ``git diff`` output into a normalized ``ChangeSet``. Handles additions,
deletions, renames, binary files, mode changes and "no newline" markers. Paths are
normalized and anything that escapes the repository root (absolute paths, ``..``
segments) is rejected: diff text can come from an untrusted PR.
"""

from __future__ import annotations

import posixpath
import re

from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import (
    ChangeSet,
    ChangeType,
    DiffLine,
    FileChange,
    Hunk,
    Language,
    LineKind,
    SkippedFile,
)

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
DIFF_GIT_RE = re.compile(r'^diff --git (?P<a>"?a/.+?"?) (?P<b>"?b/.+"?)$')

EXTENSION_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".mts": Language.TYPESCRIPT,
    ".cts": Language.TYPESCRIPT,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
}


class DiffParseError(SentinelError, ValueError):
    pass


class UnsafePathError(DiffParseError):
    pass


def detect_language(path: str) -> Language:
    ext = posixpath.splitext(path.lower())[1]
    return EXTENSION_LANGUAGE.get(ext, Language.OTHER)


def safe_path(raw: str) -> str:
    """Normalize a repository-relative path, rejecting anything that escapes the root."""
    if "\x00" in raw:
        raise UnsafePathError(f"path contains NUL byte: {raw!r}")
    path = raw.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise UnsafePathError(f"absolute path in diff: {raw!r}")
    norm = posixpath.normpath(path)
    if norm == "." or norm.startswith("../") or norm == "..":
        raise UnsafePathError(f"path escapes repository root: {raw!r}")
    return norm


def _unquote(path: str) -> str:
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        inner = path[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    return path


def _strip_prefix(path: str) -> str | None:
    path = _unquote(path)
    if path == "/dev/null":
        return None
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


class _FileBuilder:
    def __init__(self, a: str | None, b: str | None) -> None:
        self.old_path = a
        self.new_path = b
        self.change_type = ChangeType.MODIFIED
        self.is_binary = False
        self.hunks: list[Hunk] = []
        self.rename = False

    def build(self) -> FileChange:
        new_path = self.new_path or self.old_path
        if new_path is None:
            raise DiffParseError("file header without any path")
        change = self.change_type
        if self.rename and change is ChangeType.MODIFIED:
            change = ChangeType.RENAMED
        path = safe_path(new_path)
        old = safe_path(self.old_path) if self.old_path else None
        return FileChange(
            path=path,
            old_path=old if old != path else None,
            change_type=change,
            language=detect_language(path),
            is_binary=self.is_binary,
            hunks=self.hunks,
        )


def parse_unified_diff(text: str, *, source: str = "diff") -> ChangeSet:
    files: list[FileChange] = []
    skipped: list[SkippedFile] = []
    current: _FileBuilder | None = None
    hunk: Hunk | None = None
    old_ln = new_ln = 0
    old_left = new_left = 0

    def flush() -> None:
        nonlocal current, hunk
        if current is None:
            return
        try:
            files.append(current.build())
        except UnsafePathError as exc:
            skipped.append(SkippedFile(path=current.new_path or "?", reason=f"unsafe path: {exc}"))
        current = None
        hunk = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")

        # Inside a hunk: consume body lines while counts remain.
        if hunk is not None and (old_left > 0 or new_left > 0):
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            tag, body = (line[:1], line[1:]) if line else (" ", "")
            if tag == "+":
                hunk.lines.append(DiffLine(kind=LineKind.ADDED, content=body, new_lineno=new_ln))
                new_ln += 1
                new_left -= 1
                continue
            if tag == "-":
                hunk.lines.append(DiffLine(kind=LineKind.REMOVED, content=body, old_lineno=old_ln))
                old_ln += 1
                old_left -= 1
                continue
            if tag == " ":
                hunk.lines.append(
                    DiffLine(
                        kind=LineKind.CONTEXT, content=body, old_lineno=old_ln, new_lineno=new_ln
                    )
                )
                old_ln += 1
                new_ln += 1
                old_left -= 1
                new_left -= 1
                continue
            # Anything else ends the hunk early (malformed/truncated diff): fall through.
            hunk = None

        if line.startswith("\\"):
            continue

        m = DIFF_GIT_RE.match(line)
        if m:
            flush()
            current = _FileBuilder(_strip_prefix(m.group("a")), _strip_prefix(m.group("b")))
            continue

        if line.startswith("--- "):
            path = _strip_prefix(line[4:].split("\t")[0])
            if current is None or current.hunks:
                # Plain `diff -u` output has no `diff --git` line between files.
                flush()
                current = _FileBuilder(path, None)
            elif path is not None:
                current.old_path = path
            if path is None:
                current.change_type = ChangeType.ADDED
            continue
        if line.startswith("+++ ") and current is not None and not current.hunks:
            path = _strip_prefix(line[4:].split("\t")[0])
            current.new_path = path
            if path is None:
                current.change_type = ChangeType.DELETED
                current.new_path = current.old_path
            continue

        if current is None:
            continue  # preamble (e.g. commit message) before the first file

        if line.startswith("new file mode"):
            current.change_type = ChangeType.ADDED
        elif line.startswith("deleted file mode"):
            current.change_type = ChangeType.DELETED
        elif line.startswith("rename from "):
            current.rename = True
            current.old_path = _unquote(line[len("rename from ") :])
        elif line.startswith("rename to "):
            current.rename = True
            current.new_path = _unquote(line[len("rename to ") :])
        elif line.startswith(("Binary files ", "GIT binary patch")):
            current.is_binary = True
        else:
            hm = HUNK_RE.match(line)
            if hm:
                old_start = int(hm.group(1))
                old_count = int(hm.group(2)) if hm.group(2) is not None else 1
                new_start = int(hm.group(3))
                new_count = int(hm.group(4)) if hm.group(4) is not None else 1
                hunk = Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    header=hm.group(5).strip(),
                )
                current.hunks.append(hunk)
                old_ln, new_ln = old_start, new_start
                old_left, new_left = old_count, new_count

    flush()
    # A new file whose `diff --git` header lacked "new file mode" (e.g. plain `diff -u`).
    for f in files:
        if (
            f.change_type is ChangeType.MODIFIED
            and f.hunks
            and all(h.old_start == 0 and h.old_count == 0 for h in f.hunks)
        ):
            f.change_type = ChangeType.ADDED
    return ChangeSet(source=source, files=files, skipped=skipped)


def render_file_diff(change: FileChange) -> str:
    """Render a FileChange back to unified-diff text (used when prompting the model)."""
    out = [f"--- a/{change.old_path or change.path}", f"+++ b/{change.path}"]
    for h in change.hunks:
        header = f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@"
        out.append(f"{header} {h.header}".rstrip())
        for ln in h.lines:
            prefix = {LineKind.ADDED: "+", LineKind.REMOVED: "-", LineKind.CONTEXT: " "}[ln.kind]
            out.append(prefix + ln.content)
    return "\n".join(out)


def whole_file_change(path: str, content: str) -> FileChange:
    """Represent an entire file as newly added (used by `sentinel review --path`)."""
    lines = content.splitlines()
    hunk = Hunk(
        old_start=0,
        old_count=0,
        new_start=1,
        new_count=len(lines),
        lines=[
            DiffLine(kind=LineKind.ADDED, content=text, new_lineno=i)
            for i, text in enumerate(lines, start=1)
        ],
    )
    safe = safe_path(path)
    return FileChange(
        path=safe,
        change_type=ChangeType.ADDED,
        language=detect_language(safe),
        hunks=[hunk] if lines else [],
    )
