"""TypeScript / JavaScript language adapter.

Primary path: shell out to ``ts_extract.js``, which uses the real TypeScript compiler
parser. Files are sent in one batch per review so Node starts once.

Fallback: when Node or the ``typescript`` package is not available, the regex extractor
in ``typescript_fallback.py`` is used instead, and every file analyzed that way is marked
so the review summary can say so.

Registered in ``registry.py``; called by the orchestrator's build-graph stage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from sentinel.analysis.ast.typescript_fallback import TS_EXTENSIONS, regex_extract
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.models import Language

EXTRACTOR = Path(__file__).with_name("ts_extract.js")
JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs")
NPM_TIMEOUT_SECONDS = 20
DEFAULT_TIMEOUT_SECONDS = 60
MAX_ERROR_CHARS = 300


@lru_cache(maxsize=8)
def _global_node_root() -> str | None:
    """Global ``node_modules`` folder (``npm root -g``), where ``typescript`` is often installed."""
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        out = subprocess.run(
            [npm, "root", "-g"], capture_output=True, text=True, timeout=NPM_TIMEOUT_SECONDS
        )
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

    def __init__(
        self, search_roots: tuple[Path, ...] = (), timeout_s: int = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.search_roots = search_roots
        self.timeout_s = timeout_s
        self._ts_module: Path | None = None
        self._resolved = False

    @property
    def node(self) -> str | None:
        """Path of the ``node`` executable, if installed."""
        return shutil.which("node")

    def toolchain(self) -> Path | None:
        """The ``typescript`` package to parse with (looked up once), or None."""
        if not self._resolved:
            self._ts_module = find_typescript_module(self.search_roots) if self.node else None
            self._resolved = True
        return self._ts_module

    def analyze(self, path: str, source: str) -> FileSymbols:
        """Analyze a single file (see ``analyze_many``)."""
        return self.analyze_many({path: source})[path]

    def analyze_many(self, files: dict[str, str]) -> dict[str, FileSymbols]:
        """Analyze many files with one Node process; fall back to regexes if that fails."""
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
        """Send the files to ``ts_extract.js`` as JSON on stdin; read FileSymbols JSON back."""
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
            raise ValueError(f"extractor failed: {proc.stderr.strip()[:MAX_ERROR_CHARS]}")
        raw = json.loads(proc.stdout)
        out: dict[str, FileSymbols] = {}
        for item in raw:
            fs = FileSymbols.model_validate(item)
            out[fs.path] = fs
        return out


class JavaScriptAnalyzer(TypeScriptAnalyzer):
    """Same extractor, registered for JavaScript file extensions."""

    language = Language.JAVASCRIPT
    extensions: tuple[str, ...] = JS_EXTENSIONS
