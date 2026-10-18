"""AI and Ruff reports of one shared default must retain evidence without duplicates."""

import pytest

from sentinel.core.domain.ai import AIReviewPayload
from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from sentinel.core.findings.dedup import deduplicate
from sentinel.core.findings.normalize import derive_tags, normalize_ai_findings


@pytest.mark.parametrize(
    "wording", ["mutable default argument", "mutable defaults", "mutable-default"]
)
def test_mutable_default_wording_has_existing_static_concept(wording: str) -> None:
    assert "mutable-default" in derive_tags(wording)
    assert "mutable-default" not in derive_tags("Explicit zero overrides the default retry count")


def test_live_shared_default_wording_merges_with_ruff_but_not_nearby_other_bug() -> None:
    payload = AIReviewPayload.model_validate(
        {
            "findings": [
                {
                    "category": "bug",
                    "severity": "medium",
                    "confidence": 0.9,
                    "file": "example.py",
                    "line": 2,
                    "line_end": 4,
                    "title": "Mutable default argument shares state across function calls",
                    "explanation": "Omitted lists retain earlier callers' labels.",
                }
            ]
        }
    )
    ai = normalize_ai_findings(payload, provider="captured-response", known_files={"example.py"})[0]
    static = Finding(
        category=Category.BUG,
        severity=Severity.MEDIUM,
        confidence=0.9,
        file="example.py",
        line_start=2,
        line_end=2,
        title="Do not use mutable data structures for argument defaults",
        source=FindingSource.STATIC_ANALYZER,
        rule_id="ruff/B006",
        origins=["ruff:B006"],
        tags=["mutable-default"],
    )
    nearby = static.model_copy(
        update={
            "id": "F-other",
            "title": "An explicit zero loses its meaning",
            "tags": ["config-default"],
            "origins": ["other:rule"],
            "rule_id": "other/rule",
        }
    )
    result = deduplicate([ai, static, nearby])
    assert len(result) == 2
    merged = next(finding for finding in result if finding.source is FindingSource.COMBINED)
    assert set(merged.origins) == {"ai:captured-response", "ruff:B006"}
    assert merged.tags == ["mutable-default"]
    assert "F-other" not in merged.merged_ids
