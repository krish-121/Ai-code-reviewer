"""Regex-based TypeScript/JavaScript extractor, used when Node or ``typescript`` is missing.

Called by ``TypeScriptAnalyzer.analyze_many`` (``typescript_analyzer.py``) as a fallback.
It recovers functions, classes, methods, imports and calls line by line. It is clearly
less precise than the compiler-based extractor (``ts_extract.js``), so every file it
produces is marked with ``FALLBACK_NOTE`` in ``parse_error`` and the review summary
says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sentinel.core.domain.code import (
    REGEX_FALLBACK_NOTE,
    CallSite,
    FileSymbols,
    ImportRef,
    Symbol,
    SymbolKind,
)
from sentinel.core.domain.models import Language

FALLBACK_NOTE = f"{REGEX_FALLBACK_NOTE} (TypeScript compiler unavailable)"
TS_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts")
MODULE_SYMBOL = "<module>"

_IDENT = r"[A-Za-z_$][\w$]*"
_FUNC_RE = re.compile(
    rf"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s*({_IDENT})\s*\(([^)]*)\)"
)
_ARROW_RE = re.compile(
    rf"^\s*(export\s+)?(?:const|let|var)\s+({_IDENT})\s*(?::[^=]+)?=\s*(async\s+)?"
    rf"(?:function\b[^(]*\(([^)]*)\)|\(([^)]*)\)\s*(?::[^=]+)?=>|({_IDENT})\s*=>)"
)
_CLASS_RE = re.compile(
    rf"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+({_IDENT})"
    r"(?:\s+extends\s+([A-Za-z_$][\w$.]*))?"
)
_METHOD_RE = re.compile(
    r"^\s+(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+)*(async\s+)?"
    rf"({_IDENT})\s*\(([^)]*)\)\s*(?::[^{{]+)?\{{"
)
_IMPORT_RE = re.compile(r"""^\s*import\s+(?:(.+?)\s+from\s+)?['"]([^'"]+)['"]""")
_IMPORT_NAME_RE = re.compile(rf"{_IDENT}(?:\s+as\s+{_IDENT})?")
_REQUIRE_RE = re.compile(
    rf"""(?:const|let|var)\s+(\{{[^}}]*\}}|{_IDENT})\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
)
_CALL_RE = re.compile(rf"(?<![\w$.])((?:this\.)?{_IDENT}(?:\.{_IDENT})*)\s*\(")
_IDENT_RE = re.compile(_IDENT)
_TEST_FILE_RE = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(^|/)__tests__/")
_SOURCE_SUFFIX_RE = re.compile(r"\.[cm]?[jt]sx?$")
_NOT_CALLS = frozenset(
    "if for while switch catch function return typeof new await super import require "
    "constructor".split()
)
_NON_CODE_PREFIXES = ("//", "*", "import ")


def regex_extract(path: str, source: str) -> FileSymbols:
    """Extract symbols, imports and calls from one file using regular expressions."""
    lines = source.splitlines()
    scan = _Scan(lines)
    scan.symbols.append(
        Symbol(
            name=path.rsplit("/", 1)[-1],
            qualified_name=MODULE_SYMBOL,
            kind=SymbolKind.MODULE,
            line_start=1,
            line_end=max(len(lines), 1),
        )
    )
    for number, line in enumerate(lines, start=1):
        scan.line(number, line)
    result = FileSymbols(
        path=path,
        language=Language.TYPESCRIPT if path.endswith(TS_EXTENSIONS) else Language.JAVASCRIPT,
        module_name=_SOURCE_SUFFIX_RE.sub("", path),
        symbols=scan.symbols,
        imports=scan.imports,
        is_test_file=bool(_TEST_FILE_RE.search(path)),
        parse_error=FALLBACK_NOTE,
        loc=len(lines),
    )
    result.calls = _calls(result, lines)
    return result


@dataclass
class _Scan:
    """Declarations found so far, plus the classes whose bodies we are inside."""

    lines: list[str]
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    class_stack: list[tuple[str, int]] = field(default_factory=list)  # (name, last line)

    @property
    def enclosing_class(self) -> str | None:
        return self.class_stack[-1][0] if self.class_stack else None

    def line(self, number: int, line: str) -> None:
        """Try each kind of declaration in turn; the first match wins."""
        while self.class_stack and number > self.class_stack[-1][1]:
            self.class_stack.pop()
        found = (
            _import(line, number)
            or self._class(line, number)
            or self._function(line, number)
            or self._method(line, number)
        )
        if isinstance(found, ImportRef):
            self.imports.append(found)
        elif isinstance(found, Symbol):
            self.symbols.append(found)

    def _class(self, line: str, number: int) -> Symbol | None:
        match = _CLASS_RE.match(line)
        if not match:
            return None
        end = _block_end(self.lines, number - 1)
        self.class_stack.append((match.group(4), end))
        return Symbol(
            name=match.group(4),
            qualified_name=match.group(4),
            kind=SymbolKind.CLASS,
            line_start=number,
            line_end=end,
            bases=[match.group(5)] if match.group(5) else [],
            exported=bool(match.group(1)),
        )

    def _function(self, line: str, number: int) -> Symbol | None:
        """``function f(...)`` or ``const f = (...) =>`` (a method when inside a class)."""
        if match := _FUNC_RE.match(line):
            name, params, is_async, exported = match.group(4, 5, 3, 1)
        elif match := _ARROW_RE.match(line):
            name, is_async, exported = match.group(2, 3, 1)
            params = match.group(4) or match.group(5) or match.group(6)
        else:
            return None
        has_body = "{" in "".join(self.lines[number - 1 : number + 1])
        parent = self.enclosing_class
        return Symbol(
            name=name,
            qualified_name=f"{parent}.{name}" if parent else name,
            kind=SymbolKind.METHOD if parent else SymbolKind.FUNCTION,
            line_start=number,
            line_end=_block_end(self.lines, number - 1) if has_body else number,
            parent=parent,
            params=_params(params),
            is_async=bool(is_async),
            exported=bool(exported),
        )

    def _method(self, line: str, number: int) -> Symbol | None:
        parent = self.enclosing_class
        match = _METHOD_RE.match(line) if parent else None
        if parent is None or match is None or match.group(2) in _NOT_CALLS:
            return None
        return Symbol(
            name=match.group(2),
            qualified_name=f"{parent}.{match.group(2)}",
            kind=SymbolKind.METHOD,
            line_start=number,
            line_end=_block_end(self.lines, number - 1),
            parent=parent,
            params=_params(match.group(3)),
            is_async=bool(match.group(1)),
        )


def _import(line: str, number: int) -> ImportRef | None:
    """An ES ``import ... from "x"`` or a CommonJS ``const x = require("x")``."""
    if match := _IMPORT_RE.match(line):
        names: list[str] = []
        aliases: dict[str, str] = {}
        for part in _IMPORT_NAME_RE.findall(match.group(1) or ""):
            original, _, alias = part.partition(" as ")
            names.append(original.strip())
            aliases[(alias or original).strip()] = original.strip()
        return ImportRef(module=match.group(2), names=names, aliases=aliases, line=number)
    if match := _REQUIRE_RE.search(line):
        local_names = _IDENT_RE.findall(match.group(1))
        return ImportRef(
            module=match.group(2),
            names=local_names,
            aliases={n: n for n in local_names},
            line=number,
        )
    return None


def _calls(result: FileSymbols, lines: list[str]) -> list[CallSite]:
    """Every ``name(`` on a code line, attributed to the innermost enclosing symbol."""
    declaration_lines = {s.line_start for s in result.symbols if s.kind is not SymbolKind.MODULE}
    calls: list[CallSite] = []
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith(_NON_CODE_PREFIXES):
            continue
        owner = result.symbol_at(number)
        in_code = owner is not None and owner.kind is not SymbolKind.CLASS
        caller = owner.qualified_name if owner is not None and in_code else MODULE_SYMBOL
        code = _after_declaration(line) if number in declaration_lines else line
        calls += [
            CallSite(caller=caller, callee=callee, line=number)
            for callee in _CALL_RE.findall(code)
            if callee.split(".")[0] not in _NOT_CALLS and callee not in _NOT_CALLS
        ]
    return calls


def _after_declaration(line: str) -> str:
    """Drop the declaration itself so ``function f(`` is not read as a call to ``f``."""
    cut = min((x for x in (line.find("{"), line.find("=>")) if x >= 0), default=len(line))
    return line[cut:]


def _block_end(lines: list[str], start: int) -> int:
    """Line number (1-based) of the ``}`` closing the block that opens at ``start``."""
    depth = 0
    seen_open = False
    for index in range(start, len(lines)):
        for char in lines[index]:
            if char == "{":
                depth += 1
                seen_open = True
            elif char == "}":
                depth -= 1
        if seen_open and depth <= 0:
            return index + 1
    return start + 1


def _params(raw: str | None) -> list[str]:
    """Parameter names from a raw parameter list, without types and defaults."""
    if not raw:
        return []
    return [p.split(":")[0].split("=")[0].strip(" ?.") for p in raw.split(",") if p.strip()]
