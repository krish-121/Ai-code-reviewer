"""Language-agnostic verification checks. They only need the code graph and sources."""

from __future__ import annotations

import re

from sentinel.core.domain.graph import GraphNode, NodeKind
from sentinel.core.domain.models import Category, CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext, reachability
from sentinel.core.verification.symbol_evidence import IGNORED_NAMES, SymbolEvidenceCheck

CALL_CHAIN = re.compile(
    r"([A-Za-z_][\w.]*)\(\)?\s*(?:calls|->|→|invokes|passes .{0,40}? to)\s*`?([A-Za-z_][\w.]*)\(?"
)
STYLE_RE = re.compile(
    r"\b(naming|rename|variable names?|camel ?case|snake_case|pep ?8|formatting|indentation|"
    r"whitespace|line (is )?too long|line length|trailing (comma|whitespace)|docstrings?|"
    r"typos?|spelling|readability|consistent style|code style|magic numbers?|unused import)\b",
    re.I,
)


class LocationCheck:
    """Does the cited file and line exist? If not, the claim is decisively contradicted."""

    name = "location"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Check the cited location against the repository snapshot."""
        if finding.file not in ctx.sources:
            if ctx.changeset.get(finding.file) is not None:
                return VerificationCheck(
                    name=self.name,
                    outcome=CheckOutcome.NEUTRAL,
                    detail=f"{finding.file} is part of the change but its content was not analyzed",
                )
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                decisive=True,
                weight=2.0,
                detail=f"`{finding.file}` does not exist in the reviewed code",
            )
        n_lines = len(ctx.lines(finding.file))
        if finding.line_start > n_lines:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                decisive=True,
                weight=2.0,
                detail=f"line {finding.line_start} is beyond the end of {finding.file} "
                f"({n_lines} lines)",
            )
        return VerificationCheck(
            name=self.name,
            outcome=CheckOutcome.SUPPORTS,
            weight=0.3,
            detail=f"{finding.location} exists",
        )


class ChangeRelevanceCheck:
    """Does the finding point at lines this change touched?"""

    name = "change-relevance"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Supports changed lines; neutral inside a changed function; else contradicts."""
        change = ctx.changeset.get(finding.file)
        if change is not None and change.touches(finding.line_start, finding.line_end, slack=2):
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.SUPPORTS,
                weight=0.5,
                detail="cited lines were changed in this diff",
            )
        node = ctx.enclosing(finding)
        if (
            change is not None
            and node is not None
            and node.line_start
            and node.line_end
            and (change.touches(node.line_start, node.line_end))
        ):
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                weight=0.5,
                detail=f"inside `{node.name}`, which this diff changed",
            )
        return VerificationCheck(
            name=self.name,
            outcome=CheckOutcome.CONTRADICTS,
            weight=0.5,
            detail="cited code is not touched by this change (pre-existing)",
        )


class CallPathCheck:
    """Evidence like "login() calls authenticate()" must match a real CALLS path."""

    name = "call-path"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Compare 'a() calls b()' claims with CALLS paths in the code graph."""
        texts = [finding.explanation, *(e.text for e in finding.evidence)]
        pairs = {(a, b) for t in texts for a, b in CALL_CHAIN.findall(t)}
        pairs = {
            (a, b)
            for a, b in pairs
            if a.split(".")[-1] not in IGNORED_NAMES and b.split(".")[-1] not in IGNORED_NAMES
        }
        if not pairs:
            return None
        confirmed: list[str] = []
        refuted: list[str] = []
        for a, b in sorted(pairs):
            srcs = ctx.graph.find_by_name(a.split(".")[-1])
            dsts = ctx.graph.find_by_name(b.split(".")[-1])
            if not srcs or not dsts:
                continue
            if any(ctx.graph.call_path(s.id, d.id, max_depth=4) for s in srcs for d in dsts):
                confirmed.append(f"{a}() → {b}()")
            else:
                refuted.append(f"{a}() → {b}()")
        if confirmed and not refuted:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.SUPPORTS,
                weight=1.0,
                detail=f"call path confirmed in code graph: {'; '.join(confirmed)}",
            )
        if refuted and not confirmed:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                weight=1.25,
                detail=f"no such call path in the code graph: {'; '.join(refuted)}",
            )
        if confirmed and refuted:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                detail=f"confirmed {', '.join(confirmed)}; not found {', '.join(refuted)}",
            )
        return None


class ReachabilityCheck:
    """Is the cited code reachable from an entry point (endpoint, CLI, main)?"""

    name = "reachability"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Weigh reachability more for security findings."""
        label, path = reachability(finding, ctx)
        weight = 0.75 if finding.category is Category.SECURITY else 0.3
        if label == "entrypoint":
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.SUPPORTS,
                weight=weight,
                detail="reachable: " + " → ".join(path),
            )
        if label == "unreachable":
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                weight=weight,
                detail="no caller or entry point reaches this code",
            )
        if label == "test-only":
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                detail="only reached from tests: " + " → ".join(path),
            )
        return None


class StaticCorroborationCheck:
    """Did a deterministic tool report the same problem at the same place?"""

    name = "static-corroboration"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Match static findings by file, nearby line and tag or category."""
        tags = set(finding.tags)
        hits: list[Finding] = []
        for s in ctx.static_findings:
            if s.file != finding.file:
                continue
            if not (s.line_start - 2 <= finding.line_end and finding.line_start - 2 <= s.line_end):
                continue
            if (tags & set(s.tags)) or (not tags and s.category is finding.category):
                hits.append(s)
        if not hits:
            return None
        producers = sorted({o for h in hits for o in h.origins})
        return VerificationCheck(
            name=self.name,
            outcome=CheckOutcome.SUPPORTS,
            weight=2.0,
            detail=f"independently reported by {', '.join(producers)}",
        )


class TestClaimCheck:
    """Claims about missing tests are checked against the TESTS/CALLS edges."""

    __test__ = False  # not a pytest test class
    name = "test-coverage"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Check 'no tests cover X' claims against the tests the graph links to X."""
        if "missing-test" not in finding.tags and finding.category is not Category.TESTS:
            return None
        node = ctx.enclosing(finding)
        if node is None:
            return None
        tests = ctx.graph.tests_for(node.id)
        changed_test_files = {f.path for f in ctx.changeset.files if _is_test_path(f.path)}
        touched = [t for t in tests if t.file in changed_test_files]
        if touched:
            names = ", ".join(t.name for t in touched[:3])
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                detail=f"updated tests call `{node.name}` ({names}); "
                "assertions and edge-case coverage are unproven",
            )
        if tests:
            names = ", ".join(t.name for t in tests[:3])
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                detail=f"existing tests call `{node.name}` ({names}) but none were updated",
            )
        return VerificationCheck(
            name=self.name,
            outcome=CheckOutcome.SUPPORTS,
            weight=1.5,
            detail=f"no test in the repository exercises `{node.name}`",
        )


def _is_test_path(path: str) -> bool:
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    return (
        base.startswith("test_")
        or base.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx"))
        or "/tests/" in f"/{low}"
        or "__tests__" in low
    )


class StyleOnlyCheck:
    """Style is opt-in: a naming/formatting remark filed as a bug is rejected."""

    name = "not-style"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Contradict findings filed as bugs whose substance is only style."""
        if finding.category is Category.STYLE:
            return None
        substantive = [t for t in finding.tags if t not in ("missing-test",)]
        text = f"{finding.title} {finding.explanation}"
        if STYLE_RE.search(finding.title) and not substantive:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                decisive=True,
                weight=1.0,
                detail=f"stylistic remark filed as {finding.category.value} (style is opt-in)",
            )
        if STYLE_RE.search(text) and not substantive and len(text) < 200:
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                weight=1.0,
                detail="reads as a style suggestion",
            )
        return None


def generic_checks() -> list[
    LocationCheck
    | ChangeRelevanceCheck
    | SymbolEvidenceCheck
    | CallPathCheck
    | ReachabilityCheck
    | StaticCorroborationCheck
    | TestClaimCheck
    | StyleOnlyCheck
]:
    """The language-independent checks, in the order they run."""
    return [
        LocationCheck(),
        ChangeRelevanceCheck(),
        SymbolEvidenceCheck(),
        CallPathCheck(),
        ReachabilityCheck(),
        StaticCorroborationCheck(),
        TestClaimCheck(),
        StyleOnlyCheck(),
    ]


def enclosing_label(node: GraphNode | None) -> str:
    """How a node is named in check details: ``search()``, ``User``, ``module level``."""
    if node is None:
        return "module level"
    return node.name if node.kind is NodeKind.CLASS else f"{node.name}()"
