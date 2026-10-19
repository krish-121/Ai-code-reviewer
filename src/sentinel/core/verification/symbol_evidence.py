"""Check cited code names without treating opaque runtime properties as nonexistent.

Called by the generic verifier list. Repository names can support structural evidence;
missing bare function calls can contradict it. An unresolved field or object member
may belong to a runtime/library value, so its absence is neutral rather than proof
that the AI invented it. This check does not establish a program's runtime behaviour.
"""

import re

from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext

IDENT_BACKTICK = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")
IDENT_CALL = re.compile(r"\b([A-Za-z_][\w.]*)\(")
IGNORED_NAMES = frozenset(
    """print len str int float bool dict list set tuple open range isinstance type super self
    this cls None True False null undefined true false json os sys re time math request
    response req res await async return if else for while try except raise console log
    Promise Error Exception ValueError TypeError KeyError""".split()
)


def _mentioned(finding: Finding) -> tuple[set[str], set[str]]:
    texts = [
        finding.title,
        finding.explanation,
        *(item.text for item in finding.evidence if item.source.startswith("ai")),
    ]
    names: set[str] = set()
    calls: set[str] = set()
    for text in texts:
        names.update(IDENT_BACKTICK.findall(text))
        calls.update(IDENT_CALL.findall(text))
    names |= calls
    names = {
        name
        for name in names
        if name.split(".")[-1] not in IGNORED_NAMES and len(name.split(".")[-1]) >= 3
    }
    return names, calls & names


def _exists(name: str, finding: Finding, ctx: VerificationContext) -> bool:
    last = name.split(".")[-1]
    if ctx.graph.find_by_name(last):
        return True
    pattern = re.compile(rf"\b{re.escape(last)}\b")
    if pattern.search(ctx.sources.get(finding.file, "")):
        return True
    return any(pattern.search(source) for source in ctx.sources.values())


class SymbolEvidenceCheck:
    """Separate missing repository function claims from unknown data/member references."""

    name = "symbols-exist"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Corroborate names, contradict invented calls, and leave opaque fields neutral."""
        names, calls = _mentioned(finding)
        if not names:
            return None
        missing = sorted(name for name in names if not _exists(name, finding, ctx))
        missing_calls = [name for name in missing if name in calls and "." not in name]
        if missing_calls:
            shown = ", ".join(f"`{name}`" for name in missing_calls[:4])
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.CONTRADICTS,
                weight=1.5 if len(missing_calls) / len(names) >= 0.5 else 0.75,
                decisive=len(missing_calls) >= 2,
                detail=f"evidence calls {shown}, which do not exist in the repository",
            )
        if missing:
            shown = ", ".join(f"`{name}`" for name in missing[:4])
            return VerificationCheck(
                name=self.name,
                outcome=CheckOutcome.NEUTRAL,
                weight=0.75,
                detail=f"unresolved identifier/property references: {shown}; "
                "absence from repository source does not establish nonexistence",
            )
        shown = ", ".join(f"`{name}`" for name in sorted(names)[:4])
        return VerificationCheck(
            name=self.name,
            outcome=CheckOutcome.SUPPORTS,
            weight=0.75,
            detail=f"referenced symbols exist: {shown}",
        )
