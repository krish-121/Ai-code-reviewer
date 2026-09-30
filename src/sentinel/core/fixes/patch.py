"""Apply search/replace edits and render unified diffs."""

from __future__ import annotations

import difflib
import hashlib
import posixpath

from sentinel.core.domain.ai import FileEdit


class PatchError(ValueError):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def apply_edits(files: dict[str, str], edits: list[FileEdit]) -> dict[str, str]:
    """Return the new content of every edited file. Every ``search`` must match once."""
    new = dict(files)
    touched: set[str] = set()
    for i, edit in enumerate(edits, start=1):
        path = posixpath.normpath(edit.file)
        if path not in new:
            raise PatchError(f"edit {i}: {edit.file} was not one of the files provided")
        if "[REDACTED:" in edit.search:
            raise PatchError(f"edit {i}: cannot edit lines that contain redacted secrets")
        if not edit.search:
            raise PatchError(f"edit {i}: empty search text")
        count = new[path].count(edit.search)
        if count == 0:
            hint = _closest(new[path], edit.search)
            raise PatchError(
                f"edit {i}: search text not found in {path}"
                + (f"; closest existing line: {hint!r}" if hint else "")
            )
        if count > 1:
            raise PatchError(
                f"edit {i}: search text occurs {count} times in {path}; include more context"
            )
        new[path] = new[path].replace(edit.search, edit.replace, 1)
        touched.add(path)
    return {p: new[p] for p in touched}


def _closest(content: str, search: str) -> str | None:
    first = next((ln for ln in search.splitlines() if ln.strip()), "")
    matches = difflib.get_close_matches(first, content.splitlines(), n=1, cutoff=0.6)
    return matches[0] if matches else None


def unified_diff(before: dict[str, str], after: dict[str, str]) -> str:
    chunks: list[str] = []
    for path in sorted(after):
        old = before.get(path, "")
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            after[path].splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        text = "".join(diff)
        if text:
            chunks.append(f"diff --git a/{path} b/{path}\n{text}")
    return "".join(chunks)
