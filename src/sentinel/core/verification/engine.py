"""Verification engine: "AI proposes, deterministic systems verify".

Each AI finding is run through a set of independent checks. A check returns SUPPORTS,
CONTRADICTS or NEUTRAL with a weight and a human-readable detail; the engine combines
them into a score in [-1, 1] and a status:

* any *decisive* contradiction          -> REJECTED  (e.g. the cited file doesn't exist,
                                                     the query is parameterized)
* score >= 0.45 with strong support     -> SUPPORTED (a deterministic probe or a static
                                                     tool independently confirms it)
* score >= 0.2                          -> LIKELY
* score > -0.25                         -> UNCERTAIN
* otherwise                             -> REJECTED

Every check is recorded, so the UI can show exactly what was verified and what wasn't.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import CodeGraph, GraphNode, NodeKind
from sentinel.core.domain.models import (
    ChangeSet,
    CheckOutcome,
    Finding,
    FindingSource,
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
)

STRONG_WEIGHT = 1.5


@dataclass
class VerificationContext:
    graph: CodeGraph
    sources: dict[str, str]
    changeset: ChangeSet
    static_findings: list[Finding] = field(default_factory=list)
    symbols: dict[str, FileSymbols] = field(default_factory=dict)

    def lines(self, path: str) -> list[str]:
        return self.sources.get(path, "").splitlines()

    def enclosing(self, finding: Finding) -> GraphNode | None:
        return self.graph.enclosing(finding.file, finding.line_start)


class Verifier(Protocol):
    name: str

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None: ...


def reachability(finding: Finding, ctx: VerificationContext) -> tuple[str, list[str]]:
    node = ctx.enclosing(finding)
    if node is None:
        return "unknown", []
    path = ctx.graph.path_from_entrypoint(node.id)
    if path is None:
        if ctx.graph.callers(node.id):
            return "unknown", []  # called, but we can't see an entry point (library code?)
        return "unreachable", []
    labels = [n.name if n.kind is NodeKind.ENDPOINT else f"{n.name}()" for n in path]
    if path[0].kind is NodeKind.TEST:
        return "test-only", labels
    return "entrypoint", labels


class VerificationEngine:
    def __init__(self, verifiers: Sequence[Verifier]) -> None:
        self.verifiers = list(verifiers)

    def verify(self, finding: Finding, ctx: VerificationContext) -> VerificationResult:
        checks: list[VerificationCheck] = []
        for v in self.verifiers:
            try:
                result = v.check(finding, ctx)
            except Exception as exc:  # a broken check must not break the review
                result = VerificationCheck(
                    name=v.name, outcome=CheckOutcome.SKIPPED, detail=f"check failed: {exc}"
                )
            if result is not None:
                checks.append(result)
        reach, path = reachability(finding, ctx)
        return self._decide(checks, reach, path)

    @staticmethod
    def _decide(checks: list[VerificationCheck], reach: str, path: list[str]) -> VerificationResult:
        active = [c for c in checks if c.outcome is not CheckOutcome.SKIPPED]
        total = sum(c.weight for c in active) or 1.0
        signed = sum(
            c.weight * (1 if c.outcome is CheckOutcome.SUPPORTS else -1)
            for c in active
            if c.outcome in (CheckOutcome.SUPPORTS, CheckOutcome.CONTRADICTS)
        )
        score = max(-1.0, min(1.0, signed / total))
        decisive = [c for c in active if c.outcome is CheckOutcome.CONTRADICTS and c.decisive]
        strong = any(
            c.outcome is CheckOutcome.SUPPORTS and c.weight >= STRONG_WEIGHT for c in active
        )
        if decisive:
            status = VerificationStatus.REJECTED
            summary = decisive[0].detail
        elif score >= 0.45 and strong:
            status = VerificationStatus.SUPPORTED
            summary = next(
                c.detail
                for c in active
                if c.outcome is CheckOutcome.SUPPORTS and c.weight >= STRONG_WEIGHT
            )
        elif score >= 0.2:
            status = VerificationStatus.LIKELY
            summary = "evidence is consistent with the claim but not independently confirmed"
        elif score > -0.25:
            status = VerificationStatus.UNCERTAIN
            summary = "not enough deterministic evidence either way"
        else:
            status = VerificationStatus.REJECTED
            summary = next(
                (c.detail for c in active if c.outcome is CheckOutcome.CONTRADICTS),
                "evidence contradicts the claim",
            )
        return VerificationResult(
            status=status,
            score=round(score, 3),
            checks=checks,
            summary=summary,
            reachability=reach,
            call_path=path,
        )

    @staticmethod
    def deterministic(finding: Finding, ctx: VerificationContext) -> VerificationResult:
        """Static findings are proven by construction; we only add reachability."""
        reach, path = reachability(finding, ctx)
        tools = ", ".join(finding.origins) or "static analysis"
        return VerificationResult(
            status=VerificationStatus.SUPPORTED,
            score=1.0,
            checks=[
                VerificationCheck(
                    name="deterministic-rule",
                    outcome=CheckOutcome.SUPPORTS,
                    detail=f"reported by deterministic analysis ({tools})",
                    weight=2.0,
                )
            ],
            summary=f"deterministic rule {finding.rule_id or tools}",
            reachability=reach,
            call_path=path,
        )


def apply_verification(finding: Finding, result: VerificationResult) -> None:
    """Fold the verification outcome into the finding's confidence and source."""
    finding.verification = result
    if finding.is_deterministic:
        return
    evidence_strength = (result.score + 1) / 2  # [0, 1]
    blended = 0.55 * finding.confidence + 0.45 * evidence_strength
    if result.status is VerificationStatus.SUPPORTED:
        blended = max(blended, 0.8)
        if finding.source is FindingSource.AI:
            finding.source = FindingSource.VERIFIED
    elif result.status is VerificationStatus.REJECTED:
        blended = min(blended, 0.2)
    finding.confidence = round(max(0.0, min(0.99, blended)), 3)
