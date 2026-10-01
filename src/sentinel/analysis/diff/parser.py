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
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
NO_NEWLINE_MARKER = "\\"  # "\ No newline at end of file"
DEV_NULL = "/dev/null"
RENAME_FROM = "rename from "
RENAME_TO = "rename to "

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
    """The diff text is malformed."""


class UnsafePathError(DiffParseError):
    """A path in the diff points outside the repository (absolute, ``..``, NUL byte)."""


def detect_language(path: str) -> Language:
    """Language of a file, from its extension."""
    ext = posixpath.splitext(path.lower())[1]
    return EXTENSION_LANGUAGE.get(ext, Language.OTHER)


def safe_path(raw: str) -> str:
    """Normalize a repository-relative path, rejecting anything that escapes the root."""
    if "\x00" in raw:
        raise UnsafePathError(f"path contains NUL byte: {raw!r}")
    path = raw.replace("\\", "/")
    if path.startswith("/") or WINDOWS_DRIVE_RE.match(path):
        raise UnsafePathError(f"absolute path in diff: {raw!r}")
    norm = posixpath.normpath(path)
    if norm == "." or norm.startswith("../") or norm == "..":
        raise UnsafePathError(f"path escapes repository root: {raw!r}")
    return norm


def parse_unified_diff(text: str, *, source: str = "diff") -> ChangeSet:
    """Parse ``git diff`` (or plain ``diff -u``) output into a ``ChangeSet``.

    Files whose paths are unsafe are not parsed; they are listed in ``ChangeSet.skipped``.
    """
    parser = _DiffParser()
    for raw_line in text.splitlines():
        parser.feed(raw_line.rstrip("\r"))
    files, skipped = parser.finish()
    return ChangeSet(source=source, files=files, skipped=skipped)


# --------------------------------------------------------------------------- internals


def _unquote(path: str) -> str:
    """Undo git's C-style quoting of unusual file names (octal escapes inside quotes)."""
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        inner = path[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    return path


def _strip_prefix(path: str) -> str | None:
    """``a/x.py`` -> ``x.py``; ``/dev/null`` (file did not exist) -> None."""
    path = _unquote(path)
    if path == DEV_NULL:
        return None
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def _header_path(line: str) -> str | None:
    """The path on a ``--- `` / ``+++ `` line (anything after a tab is a timestamp)."""
    return _strip_prefix(line[len("--- ") :].split("\t")[0])


class _FileBuilder:
    """Collects what the diff says about one file until the next file starts."""

    def __init__(self, a: str | None, b: str | None) -> None:
        self.old_path = a
        self.new_path = b
        self.change_type = ChangeType.MODIFIED
        self.is_binary = False
        self.hunks: list[Hunk] = []
        self.rename = False

    def build(self) -> FileChange:
        """Validate the paths and produce the ``FileChange``."""
        new_path = self.new_path or self.old_path
        if new_path is None:
            raise DiffParseError("file header without any path")
        change = self.change_type
        if self.rename and change is ChangeType.MODIFIED:
            change = ChangeType.RENAMED
        if change is ChangeType.MODIFIED and _only_additions(self.hunks):
            # A new file whose header lacked "new file mode" (e.g. plain `diff -u`).
            change = ChangeType.ADDED
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


def _only_additions(hunks: list[Hunk]) -> bool:
    return bool(hunks) and all(h.old_start == 0 and h.old_count == 0 for h in hunks)


class _HunkCursor:
    """Tracks line numbers while the body of one hunk is read."""

    def __init__(self, hunk: Hunk) -> None:
        self.hunk = hunk
        self.old_line, self.new_line = hunk.old_start, hunk.new_start
        self.old_left, self.new_left = hunk.old_count, hunk.new_count

    @property
    def open(self) -> bool:
        """True while the hunk header promised more lines than were read."""
        return self.old_left > 0 or self.new_left > 0

    def consume(self, line: str) -> bool:
        """Add one body line. Returns False if the line is not a hunk line (diff truncated)."""
        tag, body = (line[:1], line[1:]) if line else (" ", "")
        if tag == "+":
            self.hunk.lines.append(
                DiffLine(kind=LineKind.ADDED, content=body, new_lineno=self.new_line)
            )
            self.new_line += 1
            self.new_left -= 1
        elif tag == "-":
            self.hunk.lines.append(
                DiffLine(kind=LineKind.REMOVED, content=body, old_lineno=self.old_line)
            )
            self.old_line += 1
            self.old_left -= 1
        elif tag == " ":
            self.hunk.lines.append(
                DiffLine(
                    kind=LineKind.CONTEXT,
                    content=body,
                    old_lineno=self.old_line,
                    new_lineno=self.new_line,
                )
            )
            self.old_line += 1
            self.new_line += 1
            self.old_left -= 1
            self.new_left -= 1
        else:
            return False
        return True


class _DiffParser:
    """Line-by-line state machine behind ``parse_unified_diff``."""

    def __init__(self) -> None:
        self.files: list[FileChange] = []
        self.skipped: list[SkippedFile] = []
        self.current: _FileBuilder | None = None
        self.cursor: _HunkCursor | None = None

    def feed(self, line: str) -> None:
        """Process one line of diff text."""
        if self.cursor is not None and self.cursor.open:
            if line.startswith(NO_NEWLINE_MARKER) or self.cursor.consume(line):
                return
            self.cursor = None  # malformed/truncated hunk: treat the line as a header
        if line.startswith(NO_NEWLINE_MARKER):
            return
        match = DIFF_GIT_RE.match(line)
        if match:
            self._flush()
            self.current = _FileBuilder(
                _strip_prefix(match.group("a")), _strip_prefix(match.group("b"))
            )
        elif line.startswith("--- "):
            self._old_file_header(_header_path(line))
        elif line.startswith("+++ ") and self.current is not None and not self.current.hunks:
            self._new_file_header(_header_path(line))
        elif self.current is not None:  # lines before the first file are a preamble
            self._file_metadata(self.current, line)

    def finish(self) -> tuple[list[FileChange], list[SkippedFile]]:
        """Close the last file and return everything parsed."""
        self._flush()
        return self.files, self.skipped

    def _old_file_header(self, path: str | None) -> None:
        if self.current is None or self.current.hunks:
            # Plain `diff -u` output has no `diff --git` line between files.
            self._flush()
            self.current = _FileBuilder(path, None)
        elif path is not None:
            self.current.old_path = path
        if path is None:
            self.current.change_type = ChangeType.ADDED

    def _new_file_header(self, path: str | None) -> None:
        assert self.current is not None
        self.current.new_path = path
        if path is None:
            self.current.change_type = ChangeType.DELETED
            self.current.new_path = self.current.old_path

    def _file_metadata(self, current: _FileBuilder, line: str) -> None:
        """Handle the extended header lines git prints, or start a new hunk."""
        if line.startswith("new file mode"):
            current.change_type = ChangeType.ADDED
        elif line.startswith("deleted file mode"):
            current.change_type = ChangeType.DELETED
        elif line.startswith(RENAME_FROM):
            current.rename = True
            current.old_path = _unquote(line[len(RENAME_FROM) :])
        elif line.startswith(RENAME_TO):
            current.rename = True
            current.new_path = _unquote(line[len(RENAME_TO) :])
        elif line.startswith(("Binary files ", "GIT binary patch")):
            current.is_binary = True
        else:
            self._maybe_start_hunk(current, line)

    def _maybe_start_hunk(self, current: _FileBuilder, line: str) -> None:
        match = HUNK_RE.match(line)
        if not match:
            return
        hunk = Hunk(
            old_start=int(match.group(1)),
            old_count=int(match.group(2)) if match.group(2) is not None else 1,
            new_start=int(match.group(3)),
            new_count=int(match.group(4)) if match.group(4) is not None else 1,
            header=match.group(5).strip(),
        )
        current.hunks.append(hunk)
        self.cursor = _HunkCursor(hunk)

    def _flush(self) -> None:
        """Finish the current file (if any) and reset per-file state."""
        if self.current is None:
            return
        try:
            self.files.append(self.current.build())
        except UnsafePathError as exc:
            self.skipped.append(
                SkippedFile(path=self.current.new_path or "?", reason=f"unsafe path: {exc}")
            )
        self.current = None
        self.cursor = None


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
