"""Language-neutral representation of what a language analyzer extracts from a file.

Language adapters (Python ``ast``, the TypeScript compiler API, ...) all produce a
``FileSymbols``. The graph builder only ever sees this shape, which is what lets a new
language be added without touching the core review engine.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from sentinel.core.domain.models import Language


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    TEST = "test"


class Symbol(BaseModel):
    name: str
    qualified_name: str = Field(description="Dotted path within the file, e.g. 'UserRepo.find'")
    kind: SymbolKind
    line_start: int
    line_end: int
    parent: str | None = Field(default=None, description="Qualified name of the enclosing class")
    decorators: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)
    bases: list[str] = Field(default_factory=list)
    is_async: bool = False
    exported: bool = False


class ImportRef(BaseModel):
    module: str = Field(description="Module specifier as written: 'app.db', './db', 'react'")
    names: list[str] = Field(default_factory=list, description="Imported names ('*' for all)")
    aliases: dict[str, str] = Field(default_factory=dict, description="local alias -> name")
    line: int = 0
    level: int = Field(default=0, description="Python relative-import level")


class CallSite(BaseModel):
    caller: str = Field(description="Qualified name of the calling symbol or '<module>'")
    callee: str = Field(description="Callee expression as written, e.g. 'self.repo.find'")
    line: int
    in_loop: bool = False
    awaited: bool = False


class EndpointRef(BaseModel):
    method: str
    route: str
    handler: str
    line: int


class DbOperation(BaseModel):
    function: str
    operation: str = Field(description="read | write | unknown")
    line: int
    detail: str = ""
    in_loop: bool = False


class FileSymbols(BaseModel):
    path: str
    language: Language
    module_name: str = ""
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[ImportRef] = Field(default_factory=list)
    calls: list[CallSite] = Field(default_factory=list)
    endpoints: list[EndpointRef] = Field(default_factory=list)
    db_operations: list[DbOperation] = Field(default_factory=list)
    is_test_file: bool = False
    parse_error: str | None = None
    loc: int = 0

    def symbol_at(self, line: int) -> Symbol | None:
        """Innermost function/method/class whose span contains ``line``."""
        best: Symbol | None = None
        for s in self.symbols:
            if s.kind is SymbolKind.MODULE or not (s.line_start <= line <= s.line_end):
                continue
            if best is None or (s.line_end - s.line_start) < (best.line_end - best.line_start):
                best = s
        return best
