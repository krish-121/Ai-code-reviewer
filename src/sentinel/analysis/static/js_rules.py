"""Sentinel's own JavaScript/TypeScript rules (line-based patterns + N+1 from symbols).

Run by ``BuiltinAnalyzer`` (``builtin_security.py``). The patterns are deliberately
narrow — each one targets a construct that is almost always a real problem — because
there is no type information to filter false positives with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sentinel.analysis.static.base import static_finding
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.models import Category, Finding, Severity

TOOL = "sentinel"
COMMENT_PREFIXES = ("//", "*", "/*")


@dataclass(frozen=True)
class JsRule:
    """One line-based rule: if ``pattern`` matches a code line, report a finding."""

    rule: str
    pattern: re.Pattern[str]
    category: Category
    severity: Severity
    confidence: float
    title: str
    tags: tuple[str, ...]
    suggested_fix: str


JS_RULES: tuple[JsRule, ...] = (
    JsRule(
        rule="sql-injection",
        pattern=re.compile(
            r"\.(query|execute|raw|\$queryRawUnsafe|\$executeRawUnsafe)\s*\("
            r"\s*(`[^`]*\$\{|['\"][^'\"]*['\"]\s*\+)"
        ),
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.85,
        title="SQL query built with string interpolation",
        tags=("sql-injection",),
        suggested_fix="Use placeholders ($1 / ?) and pass values as a separate array.",
    ),
    JsRule(
        rule="code-injection",
        pattern=re.compile(r"(?<![\w.])(eval|new\s+Function)\s*\((?!\s*['\"`][^'\"`]*['\"`]\s*\))"),
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.8,
        title="Dynamic code execution",
        tags=("code-injection",),
        suggested_fix="Avoid eval/new Function; parse the data explicitly.",
    ),
    JsRule(
        rule="command-injection",
        pattern=re.compile(r"\b(exec|execSync)\s*\(\s*(`[^`]*\$\{|['\"][^'\"]*['\"]\s*\+)"),
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.8,
        title="Shell command built from a variable",
        tags=("command-injection",),
        suggested_fix="Use execFile/spawn with an argument array.",
    ),
    JsRule(
        rule="xss",
        pattern=re.compile(
            r"(\.innerHTML\s*=(?!\s*['\"`][^'\"`$]*['\"`]\s*;?$)|dangerouslySetInnerHTML)"
        ),
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        confidence=0.6,
        title="HTML injected without escaping",
        tags=("xss",),
        suggested_fix="Use textContent or sanitize the HTML (e.g. DOMPurify).",
    ),
    JsRule(
        rule="tls-verify-disabled",
        pattern=re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"),
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        confidence=0.85,
        title="TLS certificate verification disabled",
        tags=("tls",),
        suggested_fix="Keep certificate verification on; configure a CA instead.",
    ),
)


def js_rule_findings(path: str, source: str) -> list[Finding]:
    """Apply every ``JS_RULES`` pattern to every non-comment line."""
    findings: list[Finding] = []
    for number, line in enumerate(source.splitlines(), start=1):
        if line.strip().startswith(COMMENT_PREFIXES):
            continue
        findings += [_finding(rule, path, number) for rule in JS_RULES if rule.pattern.search(line)]
    return findings


def symbols_db_in_loop(fs: FileSymbols) -> list[Finding]:
    """Language-neutral N+1 detection from extracted symbols (used for JS/TS)."""
    findings: list[Finding] = []
    reported: set[str] = set()
    for op in fs.db_operations:
        if not op.in_loop or op.function in reported:
            continue
        reported.add(op.function)
        findings.append(
            static_finding(
                tool=TOOL,
                rule="n-plus-one",
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM,
                confidence=0.7,
                line=op.line,
                file=fs.path,
                title="Database query inside a loop (N+1 queries)",
                explanation=(
                    f"`{op.detail}` in `{op.function}` runs once per loop iteration, issuing "
                    "one round trip per element."
                ),
                tags=["n+1"],
                suggested_fix="Batch the lookups into one query before the loop.",
            )
        )
    return findings


def _finding(rule: JsRule, path: str, line: int) -> Finding:
    return static_finding(
        tool=TOOL,
        rule=rule.rule,
        category=rule.category,
        severity=rule.severity,
        confidence=rule.confidence,
        title=rule.title,
        file=path,
        line=line,
        tags=list(rule.tags),
        suggested_fix=rule.suggested_fix,
        explanation=f"{rule.title} at line {line}.",
    )
