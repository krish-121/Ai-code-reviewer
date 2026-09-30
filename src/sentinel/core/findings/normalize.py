"""Turn raw AI output into domain findings, and tag findings with concepts."""

from __future__ import annotations

import re

from sentinel.core.domain.ai import AIReviewPayload
from sentinel.core.domain.models import Evidence, Finding, FindingSource

TAG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tag, re.compile(p, re.I))
    for tag, p in (
        (
            "sql-injection",
            r"sql[- ]?injection|\bsqli\b|sql (query|string|statement)s? (is |are )?"
            r"(built|constructed|formatted|interpolat)|interpolat\w* .{0,30}\bsql\b|"
            r"string-based query",
        ),
        ("command-injection", r"command injection|shell injection|os\.system|shell=true"),
        ("code-injection", r"code injection|\beval\(|\bexec\(|new Function"),
        ("xss", r"\bxss\b|cross[- ]site scripting|innerhtml|dangerouslysetinnerhtml"),
        (
            "n+1",
            r"n\s?\+\s?1|quer(y|ies) (inside|in|within) (a |the )?loop|per[- ]iteration "
            r"quer|one query per",
        ),
        (
            "blocking-in-async",
            r"block\w* (the )?event loop|blocking (call|i/o|io|operation)|"
            r"synchronous \w+ (call )?(in|inside) (an )?async|time\.sleep\(.{0,40}async",
        ),
        (
            "missing-await",
            r"(not|never) awaited|missing await|without (an )?await|forgot(ten)? "
            r"(to )?await",
        ),
        ("quadratic", r"o\(n\s?\^?\s?2\)|o\(n²\)|o\(n\s?\*\s?m\)|o\(n·m\)|quadratic|nested loops?"),
        (
            "secret",
            r"hard[- ]?coded (secret|password|credential|api key|key|token)|"
            r"(secret|credential|api key|token) (is )?(committed|hard[- ]?coded|in source)|"
            r"leaked (secret|key|credential)",
        ),
        (
            "auth",
            r"authori[sz]ation|authenticat|access control|privilege|permission|is_admin|"
            r"role check",
        ),
        (
            "race-condition",
            r"race condition|concurrent (access|modification)|not atomic|"
            r"toctou|lost update",
        ),
        (
            "swallowed-exception",
            r"swallow\w*|silently (ignor|discard)|bare except|except\w*:?\s*"
            r"pass|empty catch",
        ),
        (
            "missing-error-handling",
            r"(no|missing|lacks?|without) (proper )?error handling|"
            r"unhandled (exception|error|rejection)|not handled",
        ),
        (
            "missing-test",
            r"no tests?\b|missing (unit |regression )?tests?|untested|without "
            r"(a |any )?tests?|not covered by tests|lacks? tests?|test coverage",
        ),
        ("prompt-injection", r"prompt[- ]injection"),
        ("path-traversal", r"path traversal|directory traversal|\.\./"),
        ("deserialization", r"deserializ|pickle|yaml\.load"),
        ("weak-crypto", r"md5|sha-?1\b|weak hash|insecure (hash|crypto)"),
    )
)


def derive_tags(*texts: str) -> list[str]:
    blob = " ".join(t for t in texts if t)
    return [tag for tag, pattern in TAG_PATTERNS if pattern.search(blob)]


def _normalize_path(raw: str, known: set[str]) -> str:
    path = raw.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if path.startswith(prefix) and path[len(prefix) :] in known:
            return path[len(prefix) :]
    path = path.removeprefix("./")
    if path in known:
        return path
    suffix_matches = [k for k in known if k.endswith("/" + path)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return path


def normalize_ai_findings(
    payload: AIReviewPayload, *, provider: str, known_files: set[str]
) -> list[Finding]:
    out: list[Finding] = []
    for raw in payload.findings:
        file = _normalize_path(raw.file, known_files)
        line_end = max(raw.line, raw.line_end or raw.line)
        evidence = [Evidence(source=f"ai:{provider}", text=e) for e in raw.evidence if e.strip()]
        out.append(
            Finding(
                category=raw.category,
                severity=raw.severity,
                confidence=raw.confidence,
                title=raw.title,
                explanation=raw.explanation,
                file=file,
                line_start=raw.line,
                line_end=line_end,
                evidence=evidence,
                suggested_fix=raw.suggested_fix,
                source=FindingSource.AI,
                origins=[f"ai:{provider}"],
                tags=derive_tags(raw.title, raw.explanation, " ".join(raw.evidence)),
            )
        )
    return out
