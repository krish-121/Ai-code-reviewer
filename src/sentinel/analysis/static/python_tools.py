"""Adapters for Python tools: Ruff, mypy, Bandit."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from sentinel.analysis.static.base import (
    ToolResult,
    find_tool,
    relpath,
    run_record,
    run_tool,
    static_finding,
)
from sentinel.core.domain.models import Category, Finding, Language, Severity
from sentinel.core.domain.ports import StaticAnalysisOutput

# --------------------------------------------------------------------------- Ruff

RUFF_SELECT = "E9,F,B,S,ASYNC"
RUFF_IGNORE = "S101,S603,S607,S404,S311,S104,E501,B905"

# Longest-prefix wins. (category, severity, confidence, tags)
RUFF_RULES: dict[str, tuple[Category, Severity, float, list[str]]] = {
    "S608": (Category.SECURITY, Severity.HIGH, 0.8, ["sql-injection"]),
    "S307": (Category.SECURITY, Severity.HIGH, 0.85, ["code-injection"]),
    "S102": (Category.SECURITY, Severity.HIGH, 0.85, ["code-injection"]),
    "S301": (Category.SECURITY, Severity.HIGH, 0.8, ["deserialization"]),
    "S302": (Category.SECURITY, Severity.HIGH, 0.8, ["deserialization"]),
    "S506": (Category.SECURITY, Severity.HIGH, 0.85, ["deserialization"]),
    "S602": (Category.SECURITY, Severity.HIGH, 0.8, ["command-injection"]),
    "S604": (Category.SECURITY, Severity.HIGH, 0.8, ["command-injection"]),
    "S605": (Category.SECURITY, Severity.HIGH, 0.8, ["command-injection"]),
    "S105": (Category.SECURITY, Severity.MEDIUM, 0.6, ["secret"]),
    "S106": (Category.SECURITY, Severity.MEDIUM, 0.6, ["secret"]),
    "S107": (Category.SECURITY, Severity.MEDIUM, 0.6, ["secret"]),
    "S324": (Category.SECURITY, Severity.MEDIUM, 0.7, ["weak-crypto"]),
    "S501": (Category.SECURITY, Severity.MEDIUM, 0.9, ["tls"]),
    "S201": (Category.SECURITY, Severity.MEDIUM, 0.9, ["debug"]),
    "S110": (Category.BUG, Severity.LOW, 0.8, ["swallowed-exception"]),
    "S112": (Category.BUG, Severity.LOW, 0.8, ["swallowed-exception"]),
    "S113": (Category.BUG, Severity.LOW, 0.8, ["timeout"]),
    "S": (Category.SECURITY, Severity.MEDIUM, 0.6, []),
    "F821": (Category.BUG, Severity.HIGH, 0.95, ["undefined-name"]),
    "F811": (Category.BUG, Severity.LOW, 0.7, []),
    "F841": (Category.STYLE, Severity.LOW, 0.9, []),
    "F401": (Category.STYLE, Severity.LOW, 0.9, []),
    "F": (Category.BUG, Severity.MEDIUM, 0.8, []),
    "E9": (Category.BUG, Severity.HIGH, 0.99, ["syntax"]),
    "B006": (Category.BUG, Severity.MEDIUM, 0.9, ["mutable-default"]),
    "B023": (Category.BUG, Severity.MEDIUM, 0.8, ["closure"]),
    "B": (Category.BUG, Severity.LOW, 0.7, []),
    "ASYNC": (Category.PERFORMANCE, Severity.MEDIUM, 0.85, ["blocking-in-async"]),
    "PERF": (Category.PERFORMANCE, Severity.LOW, 0.7, []),
}


def _rule_meta(code: str) -> tuple[Category, Severity, float, list[str]]:
    for i in range(len(code), 0, -1):
        meta = RUFF_RULES.get(code[:i])
        if meta:
            return meta
    return (Category.BUG, Severity.LOW, 0.6, [])


class RuffAnalyzer:
    name = "ruff"
    languages = frozenset({Language.PYTHON})

    def __init__(self, timeout_s: int = 120, *, trust_workspace: bool = True) -> None:
        self.timeout_s = timeout_s
        # Never run binaries/plugins shipped inside an untrusted checkout (e.g. a PR).
        self.trust_workspace = trust_workspace

    def is_available(self) -> bool:
        return find_tool("ruff") is not None

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        exe = find_tool("ruff", workspace if self.trust_workspace else None)
        if exe is None or not files:
            return StaticAnalysisOutput(run_record(self.name, None, 0, "ruff not installed"))
        cmd = [
            exe,
            "check",
            "--isolated",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            RUFF_SELECT,
            "--ignore",
            RUFF_IGNORE,
            "--exit-zero",
            "--",
            *files,
        ]
        result = run_tool(cmd, workspace, self.timeout_s)
        findings = self.parse(result.stdout, workspace) if not result.timed_out else []
        return StaticAnalysisOutput(run_record(self.name, result, len(findings)), findings)

    @staticmethod
    def parse(stdout: str, workspace: Path) -> list[Finding]:
        try:
            items = json.loads(stdout or "[]")
        except json.JSONDecodeError:
            return []
        out: list[Finding] = []
        for item in items:
            code = item.get("code") or "E999"
            category, severity, confidence, tags = _rule_meta(code)
            loc = item.get("location") or {}
            end = item.get("end_location") or loc
            message = item.get("message", code)
            out.append(
                static_finding(
                    tool="ruff",
                    rule=code,
                    category=category,
                    severity=severity,
                    confidence=confidence,
                    title=message,
                    file=relpath(item.get("filename", ""), workspace),
                    line=int(loc.get("row", 1)),
                    end_line=int(end.get("row", loc.get("row", 1))),
                    tags=list(tags),
                    evidence=f"ruff {code}: {message}",
                )
            )
        return out


# --------------------------------------------------------------------------- mypy

MYPY_IMPORTANT = {
    "arg-type",
    "call-arg",
    "return-value",
    "attr-defined",
    "union-attr",
    "index",
    "operator",
    "call-overload",
    "name-defined",
    "assignment",
    "func-returns-value",
    "override",
    "has-type",
    "misc",
    "return",
    "unused-coroutine",
    "truthy-function",
}
MYPY_TAGS = {"unused-coroutine": ["missing-await"], "union-attr": ["none-check"]}
MYPY_TEXT_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)? (?P<sev>error|note|warning): "
    r"(?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)


class MypyAnalyzer:
    name = "mypy"
    languages = frozenset({Language.PYTHON})

    def __init__(self, timeout_s: int = 180, *, trust_workspace: bool = True) -> None:
        self.timeout_s = timeout_s
        # Never run binaries/plugins shipped inside an untrusted checkout (e.g. a PR).
        self.trust_workspace = trust_workspace

    def is_available(self) -> bool:
        return find_tool("mypy") is not None

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        exe = find_tool("mypy", workspace if self.trust_workspace else None)
        if exe is None or not files:
            return StaticAnalysisOutput(run_record(self.name, None, 0, "mypy not installed"))
        base = [
            exe,
            "--ignore-missing-imports",
            "--follow-imports=silent",
            "--no-error-summary",
            "--show-error-codes",
            "--show-column-numbers",
            "--no-incremental",
            "--no-pretty",
            "--no-color-output",
        ]
        # Never leave a .mypy_cache behind in the reviewed repository.
        with tempfile.TemporaryDirectory(prefix="sentinel-mypy-") as cache:
            base.append(f"--cache-dir={cache}")
            if not self.trust_workspace:
                # A repository's mypy config can load plugins (arbitrary code): ignore it.
                isolated = Path(cache) / "isolated.ini"
                isolated.write_text("[mypy]\n", encoding="utf-8")
                base.append(f"--config-file={isolated}")
            result = run_tool([*base, "-O", "json", "--", *files], workspace, self.timeout_s)
            if "unrecognized arguments" in result.stderr or "invalid choice" in result.stderr:
                result = run_tool([*base, "--", *files], workspace, self.timeout_s)
        findings = [] if result.timed_out else self.parse(result.stdout, workspace)
        return StaticAnalysisOutput(run_record(self.name, result, len(findings)), findings)

    @staticmethod
    def parse(stdout: str, workspace: Path) -> list[Finding]:
        out: list[Finding] = []
        for raw in stdout.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            item: dict[str, object]
            if raw.startswith("{"):
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
            else:
                m = MYPY_TEXT_RE.match(raw)
                if not m:
                    continue
                item = {
                    "file": m["file"],
                    "line": int(m["line"]),
                    "message": m["msg"],
                    "code": m["code"],
                    "severity": m["sev"],
                }
            code = str(item.get("code") or "")
            if item.get("severity") != "error" or code not in MYPY_IMPORTANT:
                continue
            line = item.get("line")
            out.append(
                static_finding(
                    tool="mypy",
                    rule=code,
                    category=Category.BUG,
                    severity=Severity.MEDIUM,
                    confidence=0.85,
                    title=str(item.get("message", "type error")),
                    file=relpath(str(item.get("file", "")), workspace),
                    line=line if isinstance(line, int) else 1,
                    tags=["type-error", *MYPY_TAGS.get(code, [])],
                )
            )
        return out


# --------------------------------------------------------------------------- Bandit

BANDIT_TAGS = {
    "B608": ["sql-injection"],
    "B602": ["command-injection"],
    "B605": ["command-injection"],
    "B307": ["code-injection"],
    "B301": ["deserialization"],
    "B506": ["deserialization"],
    "B105": ["secret"],
    "B106": ["secret"],
    "B303": ["weak-crypto"],
    "B324": ["weak-crypto"],
    "B501": ["tls"],
    "B201": ["debug"],
    "B110": ["swallowed-exception"],
}
BANDIT_SKIP = {"B101", "B404", "B603", "B607", "B311"}
_SEV = {"HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW}
_CONF = {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.45}


class BanditAnalyzer:
    name = "bandit"
    languages = frozenset({Language.PYTHON})

    def __init__(self, timeout_s: int = 120, *, trust_workspace: bool = True) -> None:
        self.timeout_s = timeout_s
        # Never run binaries/plugins shipped inside an untrusted checkout (e.g. a PR).
        self.trust_workspace = trust_workspace

    def is_available(self) -> bool:
        return find_tool("bandit") is not None

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        exe = find_tool("bandit", workspace if self.trust_workspace else None)
        if exe is None or not files:
            return StaticAnalysisOutput(run_record(self.name, None, 0, "bandit not installed"))
        result: ToolResult = run_tool(
            [exe, "-f", "json", "-q", "--", *files], workspace, self.timeout_s
        )
        findings = [] if result.timed_out else self.parse(result.stdout, workspace)
        return StaticAnalysisOutput(run_record(self.name, result, len(findings)), findings)

    @staticmethod
    def parse(stdout: str, workspace: Path) -> list[Finding]:
        start = stdout.find("{")
        try:
            data = json.loads(stdout[start:]) if start >= 0 else {}
        except json.JSONDecodeError:
            return []
        out: list[Finding] = []
        for r in data.get("results", []):
            test_id = r.get("test_id", "B000")
            if test_id in BANDIT_SKIP:
                continue
            severity = _SEV.get(str(r.get("issue_severity", "LOW")).upper(), Severity.LOW)
            if test_id == "B608":
                severity = Severity.HIGH
            line_range = r.get("line_range") or [r.get("line_number", 1)]
            cwe = (r.get("issue_cwe") or {}).get("id")
            out.append(
                static_finding(
                    tool="bandit",
                    rule=test_id,
                    category=Category.SECURITY,
                    severity=severity,
                    confidence=_CONF.get(str(r.get("issue_confidence", "LOW")).upper(), 0.45),
                    title=r.get("issue_text", test_id),
                    file=relpath(r.get("filename", ""), workspace),
                    line=int(r.get("line_number", 1)),
                    end_line=int(max(line_range)),
                    tags=BANDIT_TAGS.get(test_id, []) + ([f"cwe-{cwe}"] if cwe else []),
                )
            )
        return out
