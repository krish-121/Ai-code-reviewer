"""Content-addressed caches.

Keys are always hashes of the *inputs* (file content, analyzer version, prompt, model),
so invalidation is automatic: if the code changes, the key changes. There is no TTL and
no way to get a stale result for changed code.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def content_key(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8", errors="surrogatepass"))
        h.update(b"\x1f")
    return h.hexdigest()


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}
        self.hits = 0
        self.misses = 0

    def get(self, namespace: str, key: str) -> str | None:
        value = self._data.get((namespace, key))
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def set(self, namespace: str, key: str, value: str) -> None:
        self._data[(namespace, key)] = value


class DiskCache:
    """One file per entry under ``<root>/<namespace>/<k[:2]>/<k>``; writes are atomic."""

    def __init__(self, root: Path, max_entry_bytes: int = 5_000_000) -> None:
        self.root = root
        self.max_entry_bytes = max_entry_bytes
        self.hits = 0
        self.misses = 0

    def _path(self, namespace: str, key: str) -> Path:
        if not key.isalnum() or not namespace.replace("-", "").replace("_", "").isalnum():
            raise ValueError("cache keys and namespaces must be alphanumeric")
        return self.root / namespace / key[:2] / key

    def get(self, namespace: str, key: str) -> str | None:
        path = self._path(namespace, key)
        try:
            value = path.read_text(encoding="utf-8")
        except OSError:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, namespace: str, key: str, value: str) -> None:
        if len(value) > self.max_entry_bytes:
            return
        path = self._path(namespace, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(value)
            os.replace(tmp, path)
        except OSError:
            return  # caching is best-effort
