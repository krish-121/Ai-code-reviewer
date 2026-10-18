"""Fingerprinting and deduplication.

A *fingerprint* identifies "the same problem" across runs and across producers: it
hashes the file, the category, the problem concept (primary tag, or the normalized
title) and the enclosing symbol — not the raw line number, so the fingerprint survives
unrelated edits that shift lines. GitHub comment dedup and finding history use it.

*Deduplication* merges findings from different producers (Ruff, Bandit, the built-in
rules, the AI) that describe one underlying issue: same file, overlapping lines, and a
shared concept tag or similar wording.
"""

from __future__ import annotations

import hashlib
import re

from sentinel.core.domain.models import (
    Category,
    Evidence,
    Finding,
    FindingSource,
    VerificationStatus,
)

STOPWORDS = frozenset(
    """a an the in of on to for with and or is are be by at from this that it its as into
    via inside possible potential may might could should function method call calls
    called code line value values used using use when""".split()
)
GENERIC_TAGS = frozenset({"async", "type-error"})
_WORD = re.compile(r"[a-z0-9]+")


def title_tokens(text: str) -> set[str]:
    """Meaningful lower-case words of a title (stop words removed)."""
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def concept(finding: Finding) -> str:
    """The problem a finding is about: its most specific tag, else title words."""
    tags = sorted(t for t in finding.tags if t not in GENERIC_TAGS and not t.startswith("cwe-"))
    if tags:
        return tags[0]
    return "-".join(sorted(title_tokens(finding.title))[:5]) or finding.category.value


def fingerprint(finding: Finding) -> str:
    """A stable id for 'this problem in this place'.

    Built from file, category, concept and enclosing symbol (or a 10-line bucket), so it survives
    small edits and lets GitHub publishing skip duplicates.
    """
    anchor = finding.symbol or f"L{finding.line_start // 10}"
    raw = "|".join(
        [finding.file, finding.category.value, concept(finding), anchor, finding.site_anchor or ""]
    )
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def _overlap(a: Finding, b: Finding, slack: int) -> bool:
    return (
        a.file == b.file
        and a.line_start - slack <= b.line_end
        and b.line_start - slack <= a.line_end
    )


def _related(a: Finding, b: Finding) -> bool:
    tags_a = {t for t in a.tags if t not in GENERIC_TAGS}
    tags_b = {t for t in b.tags if t not in GENERIC_TAGS}
    if tags_a & tags_b:
        return True
    if tags_a and tags_b:
        return False  # both tagged with different concepts: different problems
    if a.category is not b.category:
        return False
    ta, tb = title_tokens(a.title), title_tokens(b.title)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.3


_SEV_RANK = {"high": 3, "medium": 2, "low": 1}
_VER_RANK = {
    VerificationStatus.SUPPORTED: 3,
    VerificationStatus.LIKELY: 2,
    VerificationStatus.UNCERTAIN: 1,
    VerificationStatus.REJECTED: 0,
}


def _primary_key(f: Finding) -> tuple[int, int, int, int, float]:
    ver = _VER_RANK[f.verification.status] if f.verification else 1
    # Prefer AI wording (it explains *why*), then a real explanation over a bare tool
    # message, then severity, then confidence.
    explained = int(bool(f.explanation) and f.explanation.strip() != f.title.strip())
    return (
        ver,
        _SEV_RANK[f.severity.value],
        int(f.source is not FindingSource.STATIC_ANALYZER),
        explained,
        f.confidence,
    )


def merge(group: list[Finding]) -> Finding:
    """Combine findings about the same problem into one, keeping all evidence and origins."""
    if len(group) == 1:
        return group[0]
    ranked = sorted(group, key=_primary_key, reverse=True)
    primary = ranked[0].model_copy(deep=True)
    evidence: list[Evidence] = []
    seen_ev: set[tuple[str, str]] = set()
    origins: list[str] = []
    tags: list[str] = []
    for f in ranked:
        for e in f.evidence:
            key = (e.source, e.text)
            if key not in seen_ev:
                seen_ev.add(key)
                evidence.append(e)
        origins.extend(o for o in f.origins if o not in origins)
        tags.extend(t for t in f.tags if t not in tags)
    # Noisy-OR: independent producers agreeing raises confidence.
    miss = 1.0
    for f in group:
        miss *= 1.0 - f.confidence
    primary.confidence = round(min(0.99, 1.0 - miss), 3)
    primary.severity = max((f.severity for f in group), key=lambda s: s.rank)
    if Category.SECURITY in {f.category for f in group}:
        primary.category = Category.SECURITY
    primary.evidence = evidence
    primary.origins = origins
    primary.tags = tags
    primary.line_start = min(f.line_start for f in group)
    primary.line_end = max(f.line_end for f in group)
    primary.suggested_fix = next((f.suggested_fix for f in ranked if f.suggested_fix), None)
    producers = {o.split(":", 1)[0] for o in origins}
    if len(producers) > 1:
        primary.source = FindingSource.COMBINED
    primary.merged_ids = [f.id for f in ranked[1:]] + [mid for f in ranked for mid in f.merged_ids]
    primary.baseline_status = _baseline_status(ranked)
    if primary.baseline_status is not None:
        primary.in_changed_lines = primary.baseline_status != "pre-existing"
    primary.fingerprint = fingerprint(primary)
    return primary


def _baseline_status(findings: list[Finding]) -> str | None:
    """A new diagnostic must not be hidden by merging it with an older one."""
    statuses = {f.baseline_status for f in findings}
    if "introduced" in statuses:
        return "introduced"
    if "unknown" in statuses:
        return "unknown"
    if "pre-existing" in statuses:
        return "pre-existing"
    return None


def _rejected(f: Finding) -> bool:
    return f.verification is not None and f.verification.status is VerificationStatus.REJECTED


def deduplicate(findings: list[Finding], slack: int = 3) -> list[Finding]:
    """Union-find over (overlapping location AND related concept)."""
    parent = list(range(len(findings)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            a, b = findings[i], findings[j]
            if _rejected(a) != _rejected(b):
                continue  # a refuted claim must not borrow credibility from a real finding
            if _overlap(a, b, slack) and _related(a, b):
                parent[find(j)] = find(i)
    groups: dict[int, list[Finding]] = {}
    for i, f in enumerate(findings):
        groups.setdefault(find(i), []).append(f)
    out = [merge(g) for g in groups.values()]
    for f in out:
        if not f.fingerprint:
            f.fingerprint = fingerprint(f)
    return out
