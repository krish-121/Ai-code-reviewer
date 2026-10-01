"""Markdown rendering of reviews for GitHub (summary comment + inline comments).

Used by ``publisher.py``, and by ``sentinel review --format markdown``. The HTML comments
(``SUMMARY_MARKER``, ``FP_MARKER``) are invisible on GitHub and let the publisher find
its own comments again on the next push.
"""

from __future__ import annotations

from sentinel.core.domain.models import (
    Finding,
    ReviewResult,
    RiskLevel,
    Severity,
    VerificationStatus,
)

SUMMARY_MARKER = "<!-- sentinel:summary -->"
FP_MARKER = "<!-- sentinel:fp={fp} -->"
SEV_ICON = {Severity.HIGH: "🔴", Severity.MEDIUM: "🟠", Severity.LOW: "🟡"}
RISK_ICON = {
    RiskLevel.HIGH: "🔴",
    RiskLevel.MEDIUM: "🟠",
    RiskLevel.LOW: "🟡",
    RiskLevel.NONE: "🟢",
}
VER_LABEL = {
    VerificationStatus.SUPPORTED: "✅ supported",
    VerificationStatus.LIKELY: "🟢 likely",
    VerificationStatus.UNCERTAIN: "❔ uncertain",
    VerificationStatus.REJECTED: "⛔ rejected",
}


MAX_EVIDENCE_ITEMS = 5
MAX_VERIFIER_LINES = 6
SHOWN_CHECK_OUTCOMES = ("supports", "contradicts")
FOOTER = "Sentinel · AI proposes, deterministic analysis verifies, you decide"


def _md_escape(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def finding_comment(f: Finding, review_url: str | None = None) -> str:
    """The inline comment for one finding, ending with its fingerprint marker."""
    ver = f.verification
    lines = [
        f"{SEV_ICON[f.severity]} **{f.severity.value.upper()} · {f.category.value}** — "
        f"**{f.title}**",
        "",
        f"Confidence **{f.confidence:.0%}** · Verification "
        f"**{VER_LABEL[ver.status] if ver else 'n/a'}** · Source `{f.source.value}`",
        "",
        f.explanation,
    ]
    if ver and ver.call_path:
        lines += ["", "**Reachable from:** " + " → ".join(f"`{p}`" for p in ver.call_path)]
    evidence = [e for e in f.evidence if e.text][:MAX_EVIDENCE_ITEMS]
    if evidence:
        lines += ["", "<details><summary>Evidence</summary>", ""]
        lines += [f"- *{e.source}*: {e.text}" for e in evidence]
        if ver:
            lines += [
                f"- *verifier/{c.name}*: {c.outcome.value} — {c.detail}"
                for c in ver.checks
                if c.outcome.value in SHOWN_CHECK_OUTCOMES
            ][:MAX_VERIFIER_LINES]
        lines += ["", "</details>"]
    if f.suggested_fix:
        lines += ["", f"**Suggested fix:** {f.suggested_fix}"]
    if review_url:
        lines += ["", f"[Open in Sentinel]({review_url}/findings/{f.id})"]
    lines += ["", FP_MARKER.format(fp=f.fingerprint)]
    return "\n".join(lines)


def summary_comment(
    result: ReviewResult,
    *,
    review_url: str | None = None,
    not_inline: list[Finding] | None = None,
) -> str:
    """The PR-level summary: counts, what matters, what was verified, every finding."""
    summary = result.summary
    lines = [
        SUMMARY_MARKER,
        f"## {RISK_ICON[summary.risk]} Sentinel review — {summary.headline}",
        "",
        *_stats_table(result),
    ]
    if summary.attention:
        lines += ["**What deserves attention**", "", *(f"- {a}" for a in summary.attention), ""]
    lines += _details("What changed", summary.what_changed)
    lines += _details("What was verified", summary.verified)
    lines += _details("What remains uncertain", summary.uncertain)
    lines += _findings_table(result.findings)
    if not_inline:
        lines += [
            f"_{len(not_inline)} finding(s) point at lines outside the diff and are listed "
            "above rather than commented inline._",
            "",
        ]
    lines.append(f"<sub>{_footer(result, review_url)}</sub>")
    return "\n".join(lines)


def _stats_table(result: ReviewResult) -> list[str]:
    stats = result.summary.stats
    by_severity = stats.by_severity
    return [
        "| Files | Added | Removed | 🔴 High | 🟠 Medium | 🟡 Low | Suppressed |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| {stats.files_reviewed} | +{stats.lines_added} | -{stats.lines_removed} "
        f"| {by_severity.get('high', 0)} | {by_severity.get('medium', 0)} "
        f"| {by_severity.get('low', 0)} | {stats.suppressed} |",
        "",
    ]


def _details(title: str, items: list[str]) -> list[str]:
    """A collapsible bullet list (nothing when ``items`` is empty)."""
    if not items:
        return []
    return [
        f"<details><summary>{title}</summary>",
        "",
        *(f"- {i}" for i in items),
        "",
        "</details>",
        "",
    ]


def _findings_table(findings: list[Finding]) -> list[str]:
    if not findings:
        return []
    rows = ["| | Finding | Location | Confidence | Verification |", "|---|---|---|---:|---|"]
    for f in findings:
        verification = VER_LABEL[f.verification.status] if f.verification else "n/a"
        rows.append(
            f"| {SEV_ICON[f.severity]} | {_md_escape(f.title)} | `{f.location}` | "
            f"{f.confidence:.0%} | {verification} |"
        )
    return [*rows, ""]


def _footer(result: ReviewResult, review_url: str | None) -> str:
    footer = FOOTER
    if result.provider:
        footer += f" · {result.provider}/{result.model}"
    if review_url:
        footer += f" · [full review]({review_url})"
    return footer
