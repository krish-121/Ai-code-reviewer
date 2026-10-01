"""Adapters for JavaScript/TypeScript tools: ESLint and the TypeScript compiler.

ESLint runs with a Sentinel-generated flat config (bug/security rules only) so results
don't depend on — or get silenced by — the project's own lint setup. TypeScript files
are linted only when ``@typescript-eslint/parser`` is installed in the project; the
type checker (``tsc``) covers them otherwise.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from sentinel.analysis.static.base import find_tool, relpath, run_record, run_tool, static_finding
from sentinel.core.domain.models import Category, Finding, Language, Severity
from sentinel.core.domain.ports import StaticAnalysisOutput

ESLINT_RULES: dict[str, tuple[Category, Severity, float, list[str]]] = {
    "no-eval": (Category.SECURITY, Severity.HIGH, 0.85, ["code-injection"]),
    "no-implied-eval": (Category.SECURITY, Severity.HIGH, 0.8, ["code-injection"]),
    "no-new-func": (Category.SECURITY, Severity.HIGH, 0.8, ["code-injection"]),
    "no-await-in-loop": (Category.PERFORMANCE, Severity.LOW, 0.6, ["await-in-loop"]),
    "require-atomic-updates": (Category.BUG, Severity.MEDIUM, 0.6, ["race-condition"]),
    "no-unreachable": (Category.BUG, Severity.MEDIUM, 0.95, []),
    "no-dupe-keys": (Category.BUG, Severity.MEDIUM, 0.95, []),
    "no-self-compare": (Category.BUG, Severity.MEDIUM, 0.9, []),
    "use-isnan": (Category.BUG, Severity.MEDIUM, 0.95, []),
    "valid-typeof": (Category.BUG, Severity.MEDIUM, 0.95, []),
    "no-unsafe-finally": (Category.BUG, Severity.MEDIUM, 0.9, []),
    "no-unsafe-negation": (Category.BUG, Severity.MEDIUM, 0.9, []),
    "no-cond-assign": (Category.BUG, Severity.MEDIUM, 0.8, []),
    "no-fallthrough": (Category.BUG, Severity.LOW, 0.7, []),
    "no-constant-condition": (Category.BUG, Severity.LOW, 0.7, []),
    "no-promise-executor-return": (Category.BUG, Severity.LOW, 0.7, []),
    "no-async-promise-executor": (Category.BUG, Severity.MEDIUM, 0.85, []),
    "no-unused-vars": (Category.STYLE, Severity.LOW, 0.8, []),
}
JS_GLOBS = ["**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs"]
TS_GLOBS = ["**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"]


def _config_source(ts_parser: Path | None) -> str:
    rules = dict.fromkeys(ESLINT_RULES, "error")
    base = {
        "ecmaVersion": "latest",
        "sourceType": "module",
        "parserOptions": {"ecmaFeatures": {"jsx": True}},
    }
    lines = [
        'import { createRequire } from "module";',
        "const require = createRequire(import.meta.url);",
        "export default [",
    ]
    lines.append(json.dumps({"files": JS_GLOBS, "languageOptions": base, "rules": rules}) + ",")
    if ts_parser is not None:
        ts_block = json.dumps({"files": TS_GLOBS, "rules": rules})[:-1]
        lines.append(
            f'{ts_block}, "languageOptions": {{"parser": require({json.dumps(str(ts_parser))}),'
            ' "sourceType": "module", "ecmaVersion": "latest"}},'
        )
    lines.append("];")
    return "\n".join(lines)


class ESLintAnalyzer:
    """Runs ESLint with a Sentinel-generated config (bug/security rules only)."""

    name = "eslint"
    languages = frozenset({Language.JAVASCRIPT, Language.TYPESCRIPT})

    def __init__(self, timeout_s: int = 120, *, trust_workspace: bool = True) -> None:
        self.timeout_s = timeout_s
        # Never run binaries/plugins shipped inside an untrusted checkout (e.g. a PR).
        self.trust_workspace = trust_workspace

    def is_available(self) -> bool:
        """True when the tool is installed on this machine."""
        return find_tool("eslint") is not None

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        """Run the tool on ``files`` inside ``workspace`` and normalize its output."""
        exe = find_tool("eslint", workspace if self.trust_workspace else None)
        if exe is None or not files:
            return StaticAnalysisOutput(run_record(self.name, None, 0, "eslint not installed"))
        ts_parser = workspace / "node_modules" / "@typescript-eslint" / "parser"
        parser = ts_parser if self.trust_workspace and ts_parser.is_dir() else None
        ts_exts = (".ts", ".tsx", ".mts", ".cts")
        targets = [f for f in files if parser is not None or not f.endswith(ts_exts)]
        if not targets:
            return StaticAnalysisOutput(
                run_record(self.name, None, 0, "TypeScript files need @typescript-eslint/parser")
            )
        with tempfile.TemporaryDirectory(prefix="sentinel-eslint-") as tmp:
            cfg = Path(tmp) / "eslint.config.mjs"
            cfg.write_text(_config_source(parser), encoding="utf-8")
            cmd = [
                exe,
                "--config",
                str(cfg),
                "--format",
                "json",
                "--no-warn-ignored",
                "--no-error-on-unmatched-pattern",
                "--",
                *targets,
            ]
            result = run_tool(cmd, workspace, self.timeout_s)
        findings = [] if result.timed_out else self.parse(result.stdout, workspace)
        detail = "" if parser else "TypeScript files skipped (no @typescript-eslint/parser)"
        return StaticAnalysisOutput(run_record(self.name, result, len(findings), detail), findings)

    @staticmethod
    def parse(stdout: str, workspace: Path) -> list[Finding]:
        """Findings from ESLint's JSON report."""
        try:
            data = json.loads(stdout or "[]")
        except json.JSONDecodeError:
            return []
        out: list[Finding] = []
        for file_result in data:
            path = relpath(file_result.get("filePath", ""), workspace)
            for msg in file_result.get("messages", []):
                rule = msg.get("ruleId")
                if msg.get("fatal") or rule is None:
                    continue
                category, severity, confidence, tags = ESLINT_RULES.get(
                    rule, (Category.BUG, Severity.LOW, 0.6, [])
                )
                out.append(
                    static_finding(
                        tool="eslint",
                        rule=rule,
                        category=category,
                        severity=severity,
                        confidence=confidence,
                        title=msg.get("message", rule),
                        file=path,
                        line=int(msg.get("line", 1)),
                        end_line=int(msg.get("endLine") or msg.get("line", 1)),
                        tags=list(tags),
                    )
                )
        return out


TSC_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<msg>.*)$"
)
TSC_HIGH = {"TS2304", "TS2552", "TS2339", "TS2551"}  # unknown names/properties


class TscAnalyzer:
    """Runs the TypeScript compiler in type-check mode (needs a tsconfig.json)."""

    name = "tsc"
    languages = frozenset({Language.TYPESCRIPT})

    def __init__(self, timeout_s: int = 240, *, trust_workspace: bool = True) -> None:
        self.timeout_s = timeout_s
        # Never run binaries/plugins shipped inside an untrusted checkout (e.g. a PR).
        self.trust_workspace = trust_workspace

    def is_available(self) -> bool:
        """True when the tool is installed on this machine."""
        return find_tool("tsc") is not None

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        """Run the tool on ``files`` inside ``workspace`` and normalize its output."""
        exe = find_tool("tsc", workspace if self.trust_workspace else None)
        if exe is None or not files:
            return StaticAnalysisOutput(run_record(self.name, None, 0, "tsc not installed"))
        if not (workspace / "tsconfig.json").is_file():
            return StaticAnalysisOutput(
                run_record(self.name, None, 0, "no tsconfig.json; type check skipped")
            )
        result = run_tool(
            [exe, "--noEmit", "--pretty", "false", "-p", "tsconfig.json"], workspace, self.timeout_s
        )
        wanted = set(files)
        findings = (
            [f for f in self.parse(result.stdout, workspace) if f.file in wanted]
            if not result.timed_out
            else []
        )
        return StaticAnalysisOutput(run_record(self.name, result, len(findings)), findings)

    @staticmethod
    def parse(stdout: str, workspace: Path) -> list[Finding]:
        """Findings from ``tsc`` diagnostics (``file(line,col): error TS...``)."""
        out: list[Finding] = []
        for raw in stdout.splitlines():
            m = TSC_RE.match(raw.strip())
            if not m:
                continue
            code = m["code"]
            out.append(
                static_finding(
                    tool="tsc",
                    rule=code,
                    category=Category.BUG,
                    severity=Severity.HIGH if code in TSC_HIGH else Severity.MEDIUM,
                    confidence=0.85,
                    title=m["msg"],
                    file=relpath(m["file"], workspace),
                    line=int(m["line"]),
                    tags=["type-error"],
                )
            )
        return out
