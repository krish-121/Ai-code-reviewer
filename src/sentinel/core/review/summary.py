"""Deterministic review summary: what changed, what matters, what was verified."""

from __future__ import annotations

from collections import Counter

from sentinel.core.domain.models import (
    AnalysisRun,
    ChangeSet,
    ChangeType,
    Finding,
    ReviewStats,
    ReviewSummary,
    RiskLevel,
    Severity,
    VerificationStatus,
)

SEVERITY_ORDER = [Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def _status(f: Finding) -> VerificationStatus:
    return f.verification.status if f.verification else VerificationStatus.UNCERTAIN


def compute_risk(findings: list[Finding]) -> RiskLevel:
    confirmed = {VerificationStatus.SUPPORTED, VerificationStatus.LIKELY}
    if any(f.severity is Severity.HIGH and _status(f) in confirmed for f in findings):
        return RiskLevel.HIGH
    if any(f.severity is Severity.HIGH for f in findings) or any(
        f.severity is Severity.MEDIUM and _status(f) in confirmed for f in findings
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
    by_sev = Counter(f.severity.value for f in surfaced)
    by_cat = Counter(f.category.value for f in surfaced)
    by_ver = Counter(_status(f).value for f in [*surfaced, *suppressed])
    stats = ReviewStats(
        files_changed=len(changeset.files) + len(changeset.skipped),
        files_reviewed=sum(1 for _ in changeset.reviewable()),
        files_skipped=len(changeset.skipped),
        lines_added=changeset.lines_added,
        lines_removed=changeset.lines_removed,
        by_severity={s.value: by_sev.get(s.value, 0) for s in SEVERITY_ORDER},
        by_category=dict(by_cat.most_common()),
        by_verification=dict(by_ver),
        suppressed=len(suppressed),
    )
    risk = compute_risk(surfaced)

    what: list[str] = []
    langs = Counter(f.language.value for f in changeset.files)
    if langs:
        what.append(
            f"{stats.files_reviewed} file(s) reviewed ("
            + ", ".join(f"{n} {lang}" for lang, n in langs.most_common())
            + f"), +{stats.lines_added} / -{stats.lines_removed} lines"
        )
    added = [f.path for f in changeset.files if f.change_type is ChangeType.ADDED]
    deleted = [f.path for f in changeset.files if f.change_type is ChangeType.DELETED]
    if added:
        what.append("Added: " + ", ".join(added[:6]) + (" …" if len(added) > 6 else ""))
    if deleted:
        what.append("Deleted: " + ", ".join(deleted[:6]) + (" …" if len(deleted) > 6 else ""))
    if changed_symbols:
        shown = ", ".join(f"`{s}`" for s in changed_symbols[:8])
        more = f" and {len(changed_symbols) - 8} more" if len(changed_symbols) > 8 else ""
        what.append(f"Changed symbols: {shown}{more}")
    if changeset.skipped:
        what.append(f"{len(changeset.skipped)} file(s) skipped (binary, generated, sensitive …)")

    attention = [f"[{f.severity.value.upper()}] {f.title} — {f.location}" for f in surfaced[:3]]

    verified: list[str] = []
    for f in surfaced:
        if f.verification and f.verification.status is VerificationStatus.SUPPORTED:
            verified.append(f"{f.title}: {f.verification.summary}")
    rejected = [f for f in suppressed if _status(f) is VerificationStatus.REJECTED]
    if rejected:
        reasons = "; ".join(
            f"“{f.title}” ({f.verification.summary if f.verification else 'rejected'})"
            for f in rejected[:3]
        )
        verified.append(f"Rejected {len(rejected)} unsupported claim(s): {reasons}")

    uncertain = [
        f"{f.title} — {f.location} ({_status(f).value})"
        for f in surfaced
        if _status(f) in (VerificationStatus.UNCERTAIN, VerificationStatus.LIKELY)
    ]
    unavailable = sorted(r.tool for r in runs if r.status == "unavailable")
    failed = sorted(r.tool for r in runs if r.status in ("failed", "timeout"))
    if unavailable:
        uncertain.append(f"Not run (not installed): {', '.join(unavailable)}")
    if failed:
        uncertain.append(f"Analyzer errors: {', '.join(failed)}")
    uncertain.extend(limitations)

    total = len(surfaced)
    if total:
        parts = [f"{by_sev[s.value]} {s.value}" for s in SEVERITY_ORDER if by_sev.get(s.value)]
        headline = f"{risk.value.upper()} risk: {', '.join(parts)} finding(s)"
    else:
        headline = "No problems found in this change"
    return ReviewSummary(
        risk=risk,
        headline=headline,
        stats=stats,
        what_changed=what,
        attention=attention,
        verified=verified,
        uncertain=uncertain,
    )
