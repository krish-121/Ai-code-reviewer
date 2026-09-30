"""Test doubles."""

from __future__ import annotations

from typing import Any

from sentinel.core.domain.ai import (
    AIFixPayload,
    AIFixResult,
    AIReviewPayload,
    AIReviewResult,
    FixRequest,
    ReviewRequest,
)
from sentinel.core.domain.models import TokenUsage


class ScriptedProvider:
    """An AIProvider that returns pre-written payloads (or raises) and records requests."""

    name = "scripted"

    def __init__(
        self,
        findings: list[dict[str, Any]] | None = None,
        *,
        fixes: list[dict[str, Any] | Exception] | None = None,
        error: Exception | None = None,
        model: str = "scripted-1",
    ) -> None:
        self.findings = findings or []
        self.fixes = list(fixes or [])
        self.error = error
        self.model = model
        self.requests: list[ReviewRequest] = []
        self.fix_requests: list[FixRequest] = []

    def review(self, request: ReviewRequest) -> AIReviewResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return AIReviewResult(
            payload=AIReviewPayload.model_validate({"findings": self.findings}),
            usage=TokenUsage(input_tokens=1200, output_tokens=300),
            model=self.model,
            provider=self.name,
        )

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        self.fix_requests.append(request)
        item = self.fixes.pop(0)
        if isinstance(item, Exception):
            raise item
        return AIFixResult(
            payload=AIFixPayload.model_validate(item),
            usage=TokenUsage(input_tokens=500, output_tokens=100),
            model=self.model,
            provider=self.name,
        )


def ai_finding(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "category": "bug",
        "severity": "medium",
        "confidence": 0.7,
        "file": "app/db.py",
        "line": 11,
        "title": "Something is wrong",
        "explanation": "Explanation.",
        "evidence": [],
    }
    base.update(kw)
    return base
