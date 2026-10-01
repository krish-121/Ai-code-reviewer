"""Working state shared by the stages of one review.

The orchestrator creates one ``PipelineState`` per review and passes it to every stage
method. Each field says which stage fills it in; later stages only read it. Defaults are
safe empties, so if a stage fails the stages after it still run on what is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sentinel.analysis.graph.context import ContextBundle
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import CodeGraph
from sentinel.core.domain.models import ChangeSet, Finding, ReviewResult


@dataclass
class PipelineState:
    """Intermediate results of one review run."""

    result: ReviewResult
    workspace: Path
    repository: str
    # filter stage: findings about the diff itself (secrets, sensitive files, injection)
    filter_findings: list[Finding] = field(default_factory=list)
    # build-graph stage
    sources: dict[str, str] = field(default_factory=dict)
    graph: CodeGraph = field(default_factory=CodeGraph)
    file_symbols: dict[str, FileSymbols] = field(default_factory=dict)
    # context stage
    bundle: ContextBundle | None = None
    # static-analysis stage
    static_findings: list[Finding] = field(default_factory=list)
    # AI stage
    ai_findings: list[Finding] = field(default_factory=list)
    # any stage: notes for the summary about what could not be fully analysed
    limitations: list[str] = field(default_factory=list)

    @property
    def changeset(self) -> ChangeSet:
        """The change under review (after the filter stage: without skipped files)."""
        return self.result.changeset

    @property
    def changed_paths(self) -> list[str]:
        """Paths of changed files that still exist."""
        return [f.path for f in self.changeset.reviewable()]

    @property
    def deterministic_findings(self) -> list[Finding]:
        """Findings that came from tools rather than the model."""
        return self.filter_findings + self.static_findings
