"""Language analyzer registry: routes files to the right adapter and caches results.

Adding a language = implement ``LanguageAnalyzer`` and register it here. Nothing in the
review engine changes.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError

from sentinel.analysis.ast.python_analyzer import PythonAnalyzer
from sentinel.analysis.ast.typescript_analyzer import JavaScriptAnalyzer, TypeScriptAnalyzer
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.ports import Cache, LanguageAnalyzer
from sentinel.infrastructure.storage.cache import content_key

ANALYZER_VERSION = "3"


class LanguageRegistry:
    def __init__(self, analyzers: list[LanguageAnalyzer], cache: Cache | None = None) -> None:
        self.analyzers = analyzers
        self.cache = cache
        self._by_ext: dict[str, LanguageAnalyzer] = {}
        for a in analyzers:
            for ext in a.extensions:
                self._by_ext[ext] = a

    def analyzer_for(self, path: str) -> LanguageAnalyzer | None:
        return self._by_ext.get(posixpath.splitext(path.lower())[1])

    def supports(self, path: str) -> bool:
        return self.analyzer_for(path) is not None

    def analyze(self, files: dict[str, str]) -> dict[str, FileSymbols]:
        results: dict[str, FileSymbols] = {}
        pending: dict[int, tuple[LanguageAnalyzer, dict[str, str]]] = {}
        keys: dict[str, str] = {}
        for path, source in files.items():
            analyzer = self.analyzer_for(path)
            if analyzer is None:
                continue
            key = content_key(ANALYZER_VERSION, analyzer.language.value, path, source)
            keys[path] = key
            cached = self.cache.get("symbols", key) if self.cache else None
            if cached is not None:
                try:
                    results[path] = FileSymbols.model_validate_json(cached)
                    continue
                except ValidationError:
                    pass
            pending.setdefault(id(analyzer), (analyzer, {}))[1][path] = source

        for analyzer, batch in pending.values():
            many = getattr(analyzer, "analyze_many", None)
            if callable(many):
                produced: dict[str, FileSymbols] = many(batch)
            else:
                produced = {p: analyzer.analyze(p, s) for p, s in batch.items()}
            for path, fs in produced.items():
                results[path] = fs
                if self.cache is not None and path in keys:
                    self.cache.set("symbols", keys[path], fs.model_dump_json())
        return results

    def stats(self, results: dict[str, FileSymbols]) -> dict[str, int]:
        by_lang: dict[str, int] = defaultdict(int)
        for fs in results.values():
            by_lang[fs.language.value] += 1
        return dict(by_lang)


def default_registry(
    search_roots: tuple[Path, ...] = (), cache: Cache | None = None
) -> LanguageRegistry:
    return LanguageRegistry(
        [PythonAnalyzer(), TypeScriptAnalyzer(search_roots), JavaScriptAnalyzer(search_roots)],
        cache=cache,
    )
