"""Deterministic review summary: what changed, what matters, what was verified (spec §18).

Called by the orchestrator's finalize stage. No AI is involved: every sentence is built
from the diff, the findings and the verification results, so the summary can never
claim something the evidence does not show.
"""

from __future__ import annotations

from collections import Counter

from sentinel.core.domain.models import (
    TOOL_PROBLEMS,
    AnalysisRun,
    ChangeSet,
    ChangeType,
    Finding,
    ReviewStats,
    ReviewSummary,
    RiskLevel,
    Severity,
    ToolStatus,
    VerificationStatus,
)

SEVERITY_ORDER = [Severity.HIGH, Severity.MEDIUM, Severity.LOW]
CONFIRMED = frozenset({VerificationStatus.SUPPORTED, VerificationStatus.LIKELY})
NOT_CERTAIN = frozenset({VerificationStatus.UNCERTAIN, VerificationStatus.LIKELY})
MAX_PATHS_LISTED = 6
MAX_SYMBOLS_LISTED = 8
MAX_ATTENTION_ITEMS = 3
MAX_REJECTIONS_LISTED = 3


def compute_risk(findings: list[Finding]) -> RiskLevel:
    """Overall risk. HIGH needs a confirmed high-severity finding; unconfirmed ones cap at MEDIUM.

    "Confirmed" means the verifier rated the finding SUPPORTED or LIKELY.
    """
    if any(f.severity is Severity.HIGH and _status(f) in CONFIRMED for f in findings):
        return RiskLevel.HIGH
    if any(f.severity is Severity.HIGH for f in findings) or any(
        f.severity is Severity.MEDIUM and _status(f) in CONFIRMED for f in findings
    ):
        return RiskLevel.MEDIUM
    if findings:
        return RiskLevel.LOW
    return RiskLevel.NONE


def build_summary(
    changeset: ChangeSet,
    surfaced: list[Finding],
    suppressed: list[Finding],
    *,
    changed_symbols: list[str],
    runs: list[AnalysisRun],
    limitations: list[str],
) -> ReviewSummary:
    """Build the summary shown at the top of a review and in the GitHub comment."""
    stats = build_stats(changeset, surfaced, suppressed)
    risk = compute_risk(surfaced)
    return ReviewSummary(
        risk=risk,
        headline="No findings confirmed; review has limitations"
        if not surfaced and limitations
        else _headline(risk, stats),
        stats=stats,
        what_changed=_what_changed(changeset, stats, changed_symbols),
        attention=[
            f"[{f.severity.value.upper()}] {f.title} — {f.location}"
            for f in surfaced[:MAX_ATTENTION_ITEMS]
        ],
        verified=_what_was_verified(surfaced, suppressed),
        uncertain=_what_is_uncertain(surfaced, runs, limitations),
    )


def build_stats(
    changeset: ChangeSet, surfaced: list[Finding], suppressed: list[Finding]
) -> ReviewStats:
    """Counts by severity, category and verification status."""
    by_severity = Counter(f.severity.value for f in surfaced)
    return ReviewStats(
        files_changed=len(changeset.files) + len(changeset.skipped),
        files_reviewed=len(changeset.files),
        files_skipped=len(changeset.skipped),
        lines_added=changeset.lines_added,
        lines_removed=changeset.lines_removed,
        by_severity={s.value: by_severity.get(s.value, 0) for s in SEVERITY_ORDER},
        by_category=dict(Counter(f.category.value for f in surfaced).most_common()),
        by_verification=dict(Counter(_status(f).value for f in [*surfaced, *suppressed])),
        suppressed=len(suppressed),
    )


def _headline(risk: RiskLevel, stats: ReviewStats) -> str:
    parts = [
        f"{stats.by_severity[s.value]} {s.value}"
        for s in SEVERITY_ORDER
        if stats.by_severity.get(s.value)
    ]
    if not parts:
        return "No problems found in this change"
    return f"{risk.value.upper()} risk: {', '.join(parts)} finding(s)"


def _what_changed(
    changeset: ChangeSet, stats: ReviewStats, changed_symbols: list[str]
) -> list[str]:
    lines: list[str] = []
    languages = Counter(f.language.value for f in changeset.files)
    if languages:
        per_language = ", ".join(f"{n} {lang}" for lang, n in languages.most_common())
        lines.append(
            f"{stats.files_reviewed} file(s) reviewed ({per_language}), "
            f"+{stats.lines_added} / -{stats.lines_removed} lines"
        )
    added = [f.path for f in changeset.files if f.change_type is ChangeType.ADDED]
    deleted = [f.path for f in changeset.files if f.change_type is ChangeType.DELETED]
    if added:
        lines.append("Added: " + _short_list(added, MAX_PATHS_LISTED))
    if deleted:
        lines.append("Deleted: " + _short_list(deleted, MAX_PATHS_LISTED))
    if changed_symbols:
        shown = ", ".join(f"`{s}`" for s in changed_symbols[:MAX_SYMBOLS_LISTED])
        hidden = len(changed_symbols) - MAX_SYMBOLS_LISTED
        more = f" and {hidden} more" if hidden > 0 else ""
        lines.append(f"Changed symbols: {shown}{more}")
    if changeset.skipped:
        lines.append(f"{len(changeset.skipped)} file(s) skipped (binary, generated, sensitive …)")
    return lines


def _what_was_verified(surfaced: list[Finding], suppressed: list[Finding]) -> list[str]:
    lines: list[str] = []
    deterministic = [f for f in surfaced if f.is_deterministic]
    if deterministic:
        tools = sorted({o.split(":", 1)[0] for f in deterministic for o in f.origins})
        lines.append(
            f"{len(deterministic)} finding(s) come from deterministic analysis "
            f"({', '.join(tools)}) and need no further verification"
        )
    lines += [
        f"{f.title}: {f.verification.summary}"
        for f in surfaced
        if not f.is_deterministic
        and f.verification is not None
        and f.verification.status is VerificationStatus.SUPPORTED
    ]
    rejected = [f for f in suppressed if _status(f) is VerificationStatus.REJECTED]
    if rejected:
        reasons = "; ".join(
            f"“{f.title}” ({f.verification.summary if f.verification else 'rejected'})"
            for f in rejected[:MAX_REJECTIONS_LISTED]
        )
        lines.append(f"Rejected {len(rejected)} unsupported claim(s): {reasons}")
    return lines


def _what_is_uncertain(
    surfaced: list[Finding], runs: list[AnalysisRun], limitations: list[str]
) -> list[str]:
    lines = [
        f"{f.title} — {f.location} ({_status(f).value})"
        for f in surfaced
        if _status(f) in NOT_CERTAIN
    ]
    unavailable = sorted(
        (f"{r.tool} ({r.detail})" if r.detail else r.tool)
        for r in runs
        if r.status == ToolStatus.UNAVAILABLE
    )
    failed = sorted(r.tool for r in runs if r.status in TOOL_PROBLEMS)
    if unavailable:
        lines.append(f"Not run: {', '.join(unavailable)}")
    if failed:
        lines.append(f"Analyzer errors: {', '.join(failed)}")
    return lines + limitations


def _short_list(items: list[str], limit: int) -> str:
    """Comma-separated items, with an ellipsis when some were left out."""
    return ", ".join(items[:limit]) + (" …" if len(items) > limit else "")


def _status(finding: Finding) -> VerificationStatus:
    """Verification status, treating unverified findings as uncertain."""
    return finding.verification.status if finding.verification else VerificationStatus.UNCERTAIN
