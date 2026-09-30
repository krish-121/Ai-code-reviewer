"""Markdown rendering of reviews for GitHub (summary comment + inline comments)."""

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


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def finding_comment(f: Finding, review_url: str | None = None) -> str:
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
    evidence = [e for e in f.evidence if e.text][:5]
    if evidence:
        lines += ["", "<details><summary>Evidence</summary>", ""]
        lines += [f"- *{e.source}*: {e.text}" for e in evidence]
        if ver:
            lines += [
                f"- *verifier/{c.name}*: {c.outcome.value} — {c.detail}"
                for c in ver.checks
                if c.outcome.value in ("supports", "contradicts")
            ][:6]
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
    s = result.summary
    st = s.stats
    sev = st.by_severity
    lines = [
        SUMMARY_MARKER,
        f"## {RISK_ICON[s.risk]} Sentinel review — {s.headline}",
        "",
        "| Files | Added | Removed | 🔴 High | 🟠 Medium | 🟡 Low | Suppressed |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| {st.files_reviewed} | +{st.lines_added} | -{st.lines_removed} | {sev.get('high', 0)} "
        f"| {sev.get('medium', 0)} | {sev.get('low', 0)} | {st.suppressed} |",
        "",
    ]
    if s.attention:
        lines += ["**What deserves attention**", ""] + [f"- {a}" for a in s.attention] + [""]
    if s.what_changed:
        lines += ["<details><summary>What changed</summary>", ""]
        lines += [f"- {w}" for w in s.what_changed] + ["", "</details>", ""]
    if s.verified:
        lines += ["<details><summary>What was verified</summary>", ""]
        lines += [f"- {v}" for v in s.verified] + ["", "</details>", ""]
    if s.uncertain:
        lines += ["<details><summary>What remains uncertain</summary>", ""]
        lines += [f"- {u}" for u in s.uncertain] + ["", "</details>", ""]
    if result.findings:
        lines += ["| | Finding | Location | Confidence | Verification |", "|---|---|---|---:|---|"]
        for f in result.findings:
            ver = VER_LABEL[f.verification.status] if f.verification else "n/a"
            lines.append(
                f"| {SEV_ICON[f.severity]} | {_md_escape(f.title)} | `{f.location}` | "
                f"{f.confidence:.0%} | {ver} |"
            )
        lines.append("")
    if not_inline:
        lines += [
            f"_{len(not_inline)} finding(s) point at lines outside the diff and are listed "
            "above rather than commented inline._",
            "",
        ]
    footer = "Sentinel · AI proposes, deterministic analysis verifies, you decide"
    if result.provider:
        footer += f" · {result.provider}/{result.model}"
    if review_url:
        footer += f" · [full review]({review_url})"
    lines.append(f"<sub>{footer}</sub>")
    return "\n".join(lines)
