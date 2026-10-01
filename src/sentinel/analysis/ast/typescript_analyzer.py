"""TypeScript / JavaScript language adapter.

Primary path: shell out to ``ts_extract.js``, which uses the real TypeScript compiler
parser. Files are sent in one batch per review so Node starts once.

Fallback: when Node or the ``typescript`` package is not available, a small regex
extractor recovers functions, classes, imports and calls. It is clearly less precise,
and every file analyzed that way is marked in ``parse_error`` so the review summary
can say so instead of silently pretending to have full structure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from sentinel.core.domain.code import (
    REGEX_FALLBACK_NOTE,
    CallSite,
    FileSymbols,
    ImportRef,
    Symbol,
    SymbolKind,
)
from sentinel.core.domain.models import Language

EXTRACTOR = Path(__file__).with_name("ts_extract.js")
TS_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts")
JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs")
FALLBACK_NOTE = f"{REGEX_FALLBACK_NOTE} (TypeScript compiler unavailable)"


@lru_cache(maxsize=8)
def _global_node_root() -> str | None:
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        out = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    root = out.stdout.strip()
    return root or None


def find_typescript_module(search_roots: tuple[Path, ...] = ()) -> Path | None:
    """Locate an installed ``typescript`` package directory."""
    candidates: list[Path] = []
    env = os.environ.get("SENTINEL_TYPESCRIPT_PATH")
    if env:
        candidates.append(Path(env))
    for root in search_roots:
        candidates.append(root / "node_modules" / "typescript")
    for part in os.environ.get("NODE_PATH", "").split(os.pathsep):
        if part:
            candidates.append(Path(part) / "typescript")
    global_root = _global_node_root()
    if global_root:
        candidates.append(Path(global_root) / "typescript")
    for c in candidates:
        if (c / "package.json").is_file():
            return c
    return None


class TypeScriptAnalyzer:
    """Handles .ts/.tsx (and, via the JavaScript subclass, .js/.jsx)."""

    language = Language.TYPESCRIPT
    extensions: tuple[str, ...] = TS_EXTENSIONS

    def __init__(self, search_roots: tuple[Path, ...] = (), timeout_s: int = 60) -> None:
        self.search_roots = search_roots
        self.timeout_s = timeout_s
        self._ts_module: Path | None = None
        self._resolved = False

    @property
    def node(self) -> str | None:
        return shutil.which("node")

    def toolchain(self) -> Path | None:
        if not self._resolved:
            self._ts_module = find_typescript_module(self.search_roots) if self.node else None
            self._resolved = True
        return self._ts_module

    def analyze(self, path: str, source: str) -> FileSymbols:
        return self.analyze_many({path: source})[path]

    def analyze_many(self, files: dict[str, str]) -> dict[str, FileSymbols]:
        if not files:
            return {}
        ts_module = self.toolchain()
        if ts_module is not None and self.node:
            try:
                return self._run_extractor(files, ts_module)
            except (OSError, subprocess.SubprocessError, ValueError, ValidationError):
                pass  # fall through to the regex extractor
        return {p: regex_extract(p, s) for p, s in files.items()}

    def _run_extractor(self, files: dict[str, str], ts_module: Path) -> dict[str, FileSymbols]:
        assert self.node is not None
        payload = json.dumps({"files": [{"path": p, "source": s} for p, s in files.items()]})
        env = {"PATH": os.environ.get("PATH", ""), "SENTINEL_TS_MODULE": str(ts_module)}
        proc = subprocess.run(
            [self.node, str(EXTRACTOR)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            env=env,
        )
        if proc.returncode != 0:
            raise ValueError(f"extractor failed: {proc.stderr.strip()[:300]}")
        raw = json.loads(proc.stdout)
        out: dict[str, FileSymbols] = {}
        for item in raw:
            fs = FileSymbols.model_validate(item)
            out[fs.path] = fs
        return out


class JavaScriptAnalyzer(TypeScriptAnalyzer):
    language = Language.JAVASCRIPT
    extensions: tuple[str, ...] = JS_EXTENSIONS


# --------------------------------------------------------------------------- fallback

_FUNC_RE = re.compile(
    r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_ARROW_RE = re.compile(
    r"^\s*(export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(async\s+)?"
    r"(?:function\b[^(]*\(([^)]*)\)|\(([^)]*)\)\s*(?::[^=]+)?=>|([A-Za-z_$][\w$]*)\s*=>)"
)
_CLASS_RE = re.compile(
    r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+([A-Za-z_$][\w$.]*))?"
)
_METHOD_RE = re.compile(
    r"^\s+(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+)*(async\s+)?"
    r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::[^{]+)?\{"
)
_IMPORT_RE = re.compile(r"""^\s*import\s+(?:(.+?)\s+from\s+)?['"]([^'"]+)['"]""")
_REQUIRE_RE = re.compile(
    r"""(?:const|let|var)\s+(\{[^}]*\}|[A-Za-z_$][\w$]*)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
)
_CALL_RE = re.compile(r"(?<![\w$.])((?:this\.)?[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "function",
    "return",
    "typeof",
    "new",
    "await",
    "super",
    "import",
    "require",
    "constructor",
}
_TEST_FILE_RE = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(^|/)__tests__/")


def _block_end(lines: list[str], start: int) -> int:
    depth = 0
    seen = False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return i + 1
    return start + 1


def _params(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.split(":")[0].split("=")[0].strip(" ?.") for p in raw.split(",") if p.strip()]


def regex_extract(path: str, source: str) -> FileSymbols:
    language = Language.TYPESCRIPT if path.endswith(TS_EXTENSIONS) else Language.JAVASCRIPT
    lines = source.splitlines()
    symbols: list[Symbol] = [
        Symbol(
            name=path.rsplit("/", 1)[-1],
            qualified_name="<module>",
            kind=SymbolKind.MODULE,
            line_start=1,
            line_end=max(len(lines), 1),
        )
    ]
    imports: list[ImportRef] = []
    class_stack: list[tuple[str, int]] = []
    for i, line in enumerate(lines, start=1):
        while class_stack and i > class_stack[-1][1]:
            class_stack.pop()
        if m := _IMPORT_RE.match(line):
            aliases: dict[str, str] = {}
            names: list[str] = []
            clause = m.group(1) or ""
            for part in re.findall(r"[A-Za-z_$][\w$]*(?:\s+as\s+[A-Za-z_$][\w$]*)?", clause):
                bits = part.split(" as ")
                names.append(bits[0].strip())
                aliases[bits[-1].strip()] = bits[0].strip()
            imports.append(ImportRef(module=m.group(2), names=names, aliases=aliases, line=i))
            continue
        if m := _REQUIRE_RE.search(line):
            target = m.group(1)
            local_names = re.findall(r"[A-Za-z_$][\w$]*", target)
            imports.append(
                ImportRef(
                    module=m.group(2),
                    names=local_names,
                    aliases={n: n for n in local_names},
                    line=i,
                )
            )
            continue
        if m := _CLASS_RE.match(line):
            end = _block_end(lines, i - 1)
            symbols.append(
                Symbol(
                    name=m.group(4),
                    qualified_name=m.group(4),
                    kind=SymbolKind.CLASS,
                    line_start=i,
                    line_end=end,
                    bases=[m.group(5)] if m.group(5) else [],
                    exported=bool(m.group(1)),
                )
            )
            class_stack.append((m.group(4), end))
            continue
        fm = _FUNC_RE.match(line)
        am = None if fm else _ARROW_RE.match(line)
        if fm or am:
            if fm:
                name, params, is_async, exported = (
                    fm.group(4),
                    fm.group(5),
                    fm.group(3),
                    fm.group(1),
                )
            else:
                assert am is not None
                name = am.group(2)
                params = am.group(4) or am.group(5) or am.group(6)
                is_async, exported = am.group(3), am.group(1)
            end = _block_end(lines, i - 1) if "{" in "".join(lines[i - 1 : i + 1]) else i
            parent = class_stack[-1][0] if class_stack else None
            symbols.append(
                Symbol(
                    name=name,
                    qualified_name=f"{parent}.{name}" if parent else name,
                    kind=SymbolKind.METHOD if parent else SymbolKind.FUNCTION,
                    line_start=i,
                    line_end=end,
                    parent=parent,
                    params=_params(params),
                    is_async=bool(is_async),
                    exported=bool(exported),
                )
            )
            continue
        if class_stack and (m := _METHOD_RE.match(line)) and m.group(2) not in _KEYWORDS:
            parent = class_stack[-1][0]
            symbols.append(
                Symbol(
                    name=m.group(2),
                    qualified_name=f"{parent}.{m.group(2)}",
                    kind=SymbolKind.METHOD,
                    line_start=i,
                    line_end=_block_end(lines, i - 1),
                    parent=parent,
                    params=_params(m.group(3)),
                    is_async=bool(m.group(1)),
                )
            )
    result = FileSymbols(
        path=path,
        language=language,
        module_name=re.sub(r"\.[cm]?[jt]sx?$", "", path),
        symbols=symbols,
        imports=imports,
        is_test_file=bool(_TEST_FILE_RE.search(path)),
        parse_error=FALLBACK_NOTE,
        loc=len(lines),
    )
    starts = {s.line_start for s in symbols if s.kind is not SymbolKind.MODULE}
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "import ")):
            continue
        owner = result.symbol_at(i)
        caller = (
            owner.qualified_name if owner and owner.kind is not SymbolKind.CLASS else "<module>"
        )
        if i in starts:
            # Drop the declaration itself so `function f(` is not read as a call to f.
            cut = min((x for x in (line.find("{"), line.find("=>")) if x >= 0), default=len(line))
            line = line[cut:]
        for callee in _CALL_RE.findall(line):
            if callee.split(".")[0] in _KEYWORDS or callee in _KEYWORDS:
                continue
            result.calls.append(CallSite(caller=caller, callee=callee, line=i))
    return result
