"""Finding normalization, fingerprints, deduplication and prioritization."""

from __future__ import annotations

from typing import Any

import pytest

from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.core.configuration.config import RepoConfig, parse_repo_config
from sentinel.core.domain.ai import AIReviewPayload
from sentinel.core.domain.models import (
    AnalysisRun,
    Category,
    Evidence,
    Finding,
    FindingSource,
    RiskLevel,
    Severity,
    VerificationResult,
    VerificationStatus,
)
from sentinel.core.findings.dedup import concept, deduplicate, fingerprint, merge
from sentinel.core.findings.normalize import derive_tags, normalize_ai_findings
from sentinel.core.findings.prioritize import change_relevance, score, select
from sentinel.core.review.summary import build_summary, compute_risk

DIFF = """\
diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -10,3 +10,3 @@
 a
-b
+c
 d
"""
CS = parse_unified_diff(DIFF)


def f(**kw: Any) -> Finding:
    base: dict[str, Any] = {
        "category": Category.SECURITY,
        "severity": Severity.HIGH,
        "confidence": 0.8,
        "title": "SQL injection",
        "file": "app/db.py",
        "line_start": 11,
        "line_end": 11,
        "source": FindingSource.AI,
        "origins": ["ai:x"],
        "tags": ["sql-injection"],
    }
    base.update(kw)
    return Finding(**base)


def verified(finding: Finding, status: VerificationStatus, reach: str = "entrypoint") -> Finding:
    finding.verification = VerificationResult(
        status=status, score=0.5, reachability=reach, summary=f"{status.value} because"
    )
    return finding


# ----------------------------------------------------------------- normalize


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("Possible SQL injection via f-string", "sql-injection"),
        ("query inside a loop causes N+1", "n+1"),
        ("time.sleep blocks the event loop", "blocking-in-async"),
        ("coroutine is never awaited", "missing-await"),
        ("O(n^2) nested loops", "quadratic"),
        ("hard-coded API key", "secret"),
        ("authorization check happens before authentication", "auth"),
        ("exception silently ignored", "swallowed-exception"),
        ("no tests cover the new branch", "missing-test"),
        ("Prompt-injection text in source", "prompt-injection"),
        ("pickle deserialization of user data", "deserialization"),
    ],
)
def test_tags_are_derived_from_finding_text(text: str, tag: str) -> None:
    assert tag in derive_tags(text)


def test_normalize_ai_findings_paths_and_fields() -> None:
    payload = AIReviewPayload.model_validate(
        {
            "findings": [
                {
                    "category": "bug",
                    "severity": "low",
                    "confidence": 0.4,
                    "file": "./app/db.py",
                    "line": 5,
                    "line_end": 3,
                    "title": "Off by one",
                    "explanation": "x",
                    "evidence": ["a", " "],
                },
                {
                    "category": "bug",
                    "severity": "low",
                    "confidence": 0.4,
                    "file": "db.py",
                    "line": 5,
                    "title": "Suffix path",
                    "explanation": "x",
                },
                {
                    "category": "bug",
                    "severity": "low",
                    "confidence": 0.4,
                    "file": "b/app/db.py",
                    "line": 5,
                    "title": "Diff prefix",
                    "explanation": "x",
                },
            ]
        }
    )
    out = normalize_ai_findings(payload, provider="claude", known_files={"app/db.py", "x/db2.py"})
    assert [x.file for x in out] == ["app/db.py"] * 3
    assert out[0].line_end == 5 and len(out[0].evidence) == 1
    assert out[0].origins == ["ai:claude"] and out[0].source is FindingSource.AI


# ----------------------------------------------------------------- fingerprint & dedup


def test_fingerprint_is_stable_across_line_shifts_with_symbol() -> None:
    a = f(symbol="find_user", line_start=11)
    b = f(symbol="find_user", line_start=40, line_end=40)
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(f(symbol="other"))
    assert concept(f(tags=[], title="Unused variable total")) == "total-unused-variable"
    assert concept(f(tags=["async", "missing-await"])) == "missing-await"


def test_dedup_merges_static_and_ai_reports() -> None:
    ai = f(
        confidence=0.7,
        explanation="AI explains why",
        suggested_fix=None,
        evidence=[Evidence(source="ai", text="login() calls find_user()")],
    )
    ruff = f(
        source=FindingSource.STATIC_ANALYZER,
        origins=["ruff:S608"],
        confidence=0.8,
        severity=Severity.MEDIUM,
        title="Possible SQL injection vector",
        line_start=12,
        line_end=12,
        suggested_fix="use params",
        evidence=[Evidence(source="ruff", text="ruff S608")],
    )
    other = f(title="Blocking call", tags=["blocking-in-async"], category=Category.PERFORMANCE)
    far = f(line_start=50, line_end=50)
    out = deduplicate([ai, ruff, other, far])
    assert len(out) == 3
    merged = next(x for x in out if x.merged_ids)
    assert merged.source is FindingSource.COMBINED
    assert merged.title == "SQL injection"  # AI wording wins
    assert merged.severity is Severity.HIGH
    assert merged.confidence == pytest.approx(0.94)
    assert (merged.line_start, merged.line_end) == (11, 12)
    assert merged.suggested_fix == "use params"
    assert set(merged.origins) == {"ai:x", "ruff:S608"}
    assert len(merged.evidence) == 2


def test_dedup_by_title_similarity_without_tags() -> None:
    a = f(tags=[], category=Category.BUG, title="Missing null check on user lookup")
    b = f(
        tags=[],
        category=Category.BUG,
        title="User lookup lacks null check",
        source=FindingSource.STATIC_ANALYZER,
        origins=["mypy:union-attr"],
    )
    c = f(tags=[], category=Category.PERFORMANCE, title="Missing null check on user lookup")
    assert len(deduplicate([a, b, c])) == 2
    assert merge([a]) is a


def test_verified_primary_preferred_over_rejected() -> None:
    rejected = verified(f(title="SQL injection maybe"), VerificationStatus.REJECTED)
    supported = verified(
        f(title="Real SQL injection", confidence=0.5), VerificationStatus.SUPPORTED
    )
    assert merge([rejected, supported]).title == "Real SQL injection"


# ----------------------------------------------------------------- prioritize & select


def test_priority_is_explainable() -> None:
    finding = verified(f(), VerificationStatus.SUPPORTED)
    p = score(finding, CS)
    assert p.score == pytest.approx(0.8)
    assert "on changed lines" in p.explanation and "entrypoint" in p.explanation
    low = verified(
        f(severity=Severity.LOW, line_start=40, line_end=40),
        VerificationStatus.UNCERTAIN,
        "unreachable",
    )
    assert score(low, CS).score < p.score
    assert change_relevance(f(file="other.py", in_changed_lines=False), CS)[0] == 0.3
    assert change_relevance(f(line_start=14, line_end=14), CS)[0] == 0.85
    assert change_relevance(f(line_start=30, line_end=30), CS)[0] == 0.5
    assert change_relevance(f(file=".env", in_changed_lines=True), CS)[0] == 1.0


def test_select_reasons() -> None:
    cfg = parse_repo_config(
        "severity_threshold: medium\nreview:\n  max_findings: 2\n  surface_uncertain: false\n"
    )
    items = [
        verified(f(title="a"), VerificationStatus.SUPPORTED),
        verified(f(title="b", tags=["x"]), VerificationStatus.SUPPORTED),
        verified(f(title="c", tags=["y"]), VerificationStatus.SUPPORTED),
        verified(f(title="rej"), VerificationStatus.REJECTED),
        verified(f(title="low", severity=Severity.LOW), VerificationStatus.SUPPORTED),
        verified(f(title="style", category=Category.STYLE), VerificationStatus.SUPPORTED),
        verified(
            f(
                title="old",
                source=FindingSource.STATIC_ANALYZER,
                origins=["ruff:F1"],
                in_changed_lines=False,
            ),
            VerificationStatus.SUPPORTED,
        ),
        verified(f(title="meh", confidence=0.1), VerificationStatus.SUPPORTED),
        verified(f(title="unsure"), VerificationStatus.UNCERTAIN),
    ]
    surfaced, suppressed = select(items, CS, cfg)
    assert len(surfaced) == 2
    reasons = {x.title: x.suppressed_reason for x in suppressed}
    assert reasons["rej"] is not None and "rejected by verification" in reasons["rej"]
    assert "below severity threshold" in (reasons["low"] or "")
    assert "not enabled" in (reasons["style"] or "")
    assert "pre-existing" in (reasons["old"] or "")
    assert "confidence" in (reasons["meh"] or "")
    assert "uncertain" in (reasons["unsure"] or "")
    assert any("display budget" in (r or "") for r in reasons.values())


# ----------------------------------------------------------------- summary


def test_risk_needs_confirmed_findings_to_be_high() -> None:
    assert compute_risk([]) is RiskLevel.NONE
    assert compute_risk([verified(f(), VerificationStatus.SUPPORTED)]) is RiskLevel.HIGH
    assert compute_risk([verified(f(), VerificationStatus.UNCERTAIN)]) is RiskLevel.MEDIUM
    assert compute_risk([verified(f(severity=Severity.MEDIUM), VerificationStatus.LIKELY)]) is (
        RiskLevel.MEDIUM
    )
    assert compute_risk([verified(f(severity=Severity.LOW), VerificationStatus.SUPPORTED)]) is (
        RiskLevel.LOW
    )


def test_summary_headline_stats_and_sections() -> None:
    surfaced = [
        verified(f(), VerificationStatus.SUPPORTED),
        verified(f(title="maybe", severity=Severity.MEDIUM), VerificationStatus.LIKELY),
    ]
    rejected = verified(f(title="nope"), VerificationStatus.REJECTED)
    cs = parse_unified_diff(
        DIFF + "diff --git a/n.ts b/n.ts\nnew file mode 100644\n--- /dev/null\n"
        "+++ b/n.ts\n@@ -0,0 +1 @@\n+x\n"
    )
    s = build_summary(
        cs,
        surfaced,
        [rejected],
        changed_symbols=[f"s{i}" for i in range(10)],
        runs=[
            AnalysisRun(tool="bandit", status="unavailable"),
            AnalysisRun(tool="ruff", status="timeout"),
        ],
        limitations=["context truncated"],
    )
    assert s.risk is RiskLevel.HIGH
    assert s.headline == "HIGH risk: 1 high, 1 medium finding(s)"
    assert s.stats.by_severity == {"high": 1, "medium": 1, "low": 0}
    assert any("Added: n.ts" in w for w in s.what_changed)
    assert any("and 2 more" in w for w in s.what_changed)
    assert s.attention[0].startswith("[HIGH] SQL injection")
    assert any("Rejected 1" in v for v in s.verified)
    assert any("maybe" in u for u in s.uncertain)
    assert "Not run (not installed): bandit" in s.uncertain
    assert "Analyzer errors: ruff" in s.uncertain
    assert "context truncated" in s.uncertain
    assert s.stats.by_verification == {"supported": 1, "likely": 1, "rejected": 1}


def test_default_config_selects_everything_reasonable() -> None:
    surfaced, suppressed = select([verified(f(), VerificationStatus.SUPPORTED)], CS, RepoConfig())
    assert len(surfaced) == 1 and not suppressed
