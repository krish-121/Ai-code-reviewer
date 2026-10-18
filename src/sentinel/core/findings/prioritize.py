"""Explainable prioritization and selection.

    priority = severity × confidence × reachability × change relevance × verification

Every factor is stored on the finding with a one-line explanation, so the UI can say
*why* one finding outranks another. Selection then decides what the developer sees:
rejected, below-threshold and over-budget findings are kept, but suppressed with a
reason, never silently dropped.
"""

from __future__ import annotations

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import (
    Category,
    ChangeSet,
    Finding,
    PriorityScore,
    Severity,
    VerificationStatus,
)

SEVERITY_WEIGHT = {Severity.HIGH: 1.0, Severity.MEDIUM: 0.6, Severity.LOW: 0.3}
REACHABILITY_WEIGHT = {"entrypoint": 1.0, "unknown": 0.85, "test-only": 0.6, "unreachable": 0.5}
VERIFICATION_WEIGHT = {
    VerificationStatus.SUPPORTED: 1.0,
    VerificationStatus.LIKELY: 0.85,
    VerificationStatus.UNCERTAIN: 0.6,
    VerificationStatus.REJECTED: 0.0,
}


def change_relevance(finding: Finding, changeset: ChangeSet) -> tuple[float, str]:
    """How strongly a finding relates to the change (1.0 on changed lines), and why."""
    change = changeset.get(finding.file)
    if change is None:
        if finding.in_changed_lines:
            return 1.0, "introduced by this change"
        return 0.3, "outside the changed files"
    if change.touches(finding.line_start, finding.line_end):
        return 1.0, "on changed lines"
    if change.touches(finding.line_start, finding.line_end, slack=5):
        return 0.85, "next to changed lines"
    return 0.5, "in a changed file, away from the change"


def score(finding: Finding, changeset: ChangeSet) -> PriorityScore:
    """Priority = severity × confidence × reachability × change relevance × verification."""
    sev = SEVERITY_WEIGHT[finding.severity]
    reach_label = finding.verification.reachability if finding.verification else "unknown"
    reach = REACHABILITY_WEIGHT.get(reach_label, 0.85)
    relevance, why = change_relevance(finding, changeset)
    ver = VERIFICATION_WEIGHT[finding.verification.status] if finding.verification else 0.6
    value = sev * finding.confidence * reach * relevance * ver
    explanation = (
        f"{finding.severity.value} severity ({sev:g}) × confidence {finding.confidence:.2f} × "
        f"reachability {reach_label} ({reach:g}) × {why} ({relevance:g}) × "
        f"verification ({ver:g}) = {value:.3f}"
    )
    return PriorityScore(
        score=round(value, 4),
        severity_weight=sev,
        confidence=finding.confidence,
        reachability=reach,
        change_relevance=relevance,
        explanation=explanation,
    )


def select(
    findings: list[Finding], changeset: ChangeSet, config: RepoConfig
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into the ones to show and the suppressed ones.

    Suppressed (with a reason): rejected by the verifier, a disabled category, below the severity or
    confidence threshold, a pre-existing tool finding outside the change, uncertain while
    ``surface_uncertain`` is off, or beyond ``max_findings``. Nothing is deleted.
    """
    enabled = set(config.review.enabled_categories())
    candidates: list[Finding] = []
    suppressed: list[Finding] = []
    for f in findings:
        f.priority = score(f, changeset)
        reason = _suppression_reason(f, enabled, config)
        if reason is None:
            candidates.append(f)
        else:
            f.suppressed_reason = reason
            suppressed.append(f)
    candidates.sort(key=lambda f: f.priority.score if f.priority else 0.0, reverse=True)
    surfaced = candidates[: config.review.max_findings]
    for f in candidates[config.review.max_findings :]:
        f.suppressed_reason = f"over the display budget of {config.review.max_findings}"
        suppressed.append(f)
    suppressed.sort(key=lambda f: f.priority.score if f.priority else 0.0, reverse=True)
    return surfaced, suppressed


def _suppression_reason(f: Finding, enabled: set[Category], config: RepoConfig) -> str | None:
    status = f.verification.status if f.verification else VerificationStatus.UNCERTAIN
    if status is VerificationStatus.REJECTED:
        summary = f.verification.summary if f.verification else ""
        return f"rejected by verification{': ' + summary if summary else ''}"
    if f.category not in enabled:
        return f"category '{f.category.value}' not enabled"
    if not f.severity.at_least(config.severity_threshold):
        return f"below severity threshold ({config.severity_threshold.value})"
    if f.baseline_status == "pre-existing":
        return "pre-existing diagnostic confirmed in the base tree"
    if not f.in_changed_lines and f.is_deterministic:
        return "pre-existing issue outside the change"
    if f.confidence < config.review.min_confidence:
        return f"confidence {f.confidence:.2f} below {config.review.min_confidence:.2f}"
    if status is VerificationStatus.UNCERTAIN and not config.review.surface_uncertain:
        return "uncertain and surface_uncertain is off"
    return None
