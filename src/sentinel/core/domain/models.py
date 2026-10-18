"""Core domain model.

Everything in this module is pure data: no I/O, no framework imports. The API, the
database layer, the CLI and the GitHub integration all translate to and from these
types, which keeps the review engine independent of how it is delivered.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- enums


class Severity(StrEnum):
    """How bad a finding is if it is real (independent of how sure we are)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Numeric order used for sorting and comparisons (HIGH=3 ... LOW=1)."""
        return {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}[self]

    def at_least(self, other: Severity) -> bool:
        """True when this severity is the same as or worse than ``other``."""
        return self.rank >= other.rank


class Category(StrEnum):
    """What kind of problem a finding describes (spec §12)."""

    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    TESTS = "tests"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    STYLE = "style"


class FindingSource(StrEnum):
    """Where a finding's claim comes from.

    AI               - produced by the language model only
    STATIC_ANALYZER  - produced by a deterministic tool (Ruff, Bandit, built-in rules...)
    VERIFIED         - an AI claim that deterministic checks confirmed
    COMBINED         - several sources reported the same underlying problem
    """

    AI = "ai"
    STATIC_ANALYZER = "static_analyzer"
    VERIFIED = "verified"
    COMBINED = "combined"


class FindingStatus(StrEnum):
    """What the user decided about a finding."""

    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    FIXED = "fixed"


class VerificationStatus(StrEnum):
    """The verifier's verdict on a finding (spec §14)."""

    SUPPORTED = "supported"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


class ChangeType(StrEnum):
    """How a file changed in the diff."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class Language(StrEnum):
    """Languages Sentinel understands; everything else is OTHER."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    OTHER = "other"


class LineKind(StrEnum):
    """Whether a diff line was added, removed or is unchanged context."""

    ADDED = "added"
    REMOVED = "removed"
    CONTEXT = "context"


class RiskLevel(StrEnum):
    """Overall risk of a change, shown in the review summary."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ReviewStatus(StrEnum):
    """Lifecycle of a review job. PARTIAL means some stages failed."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class StageName(StrEnum):
    """The pipeline stages, in the order the orchestrator runs them."""

    PARSE_DIFF = "parse_diff"
    FILTER_FILES = "filter_files"
    BUILD_GRAPH = "build_graph"
    EXTRACT_CONTEXT = "extract_context"
    STATIC_ANALYSIS = "static_analysis"
    AI_REVIEW = "ai_review"
    VERIFICATION = "verification"
    FINALIZE = "finalize"


STAGE_LABELS: dict[StageName, str] = {
    StageName.PARSE_DIFF: "Parsing diff",
    StageName.FILTER_FILES: "Filtering files & secrets",
    StageName.BUILD_GRAPH: "Building code graph",
    StageName.EXTRACT_CONTEXT: "Extracting context",
    StageName.STATIC_ANALYSIS: "Running static analysis",
    StageName.AI_REVIEW: "AI review",
    StageName.VERIFICATION: "Verification",
    StageName.FINALIZE: "Finalizing",
}


class StageStatus(StrEnum):
    """Progress state of one pipeline stage."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


def new_id(prefix: str) -> str:
    """Return a short random id such as ``F-1a2b3c4d5e`` (prefix + 10 hex chars)."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    """Timezone-aware current time in UTC (one place, so tests can reason about it)."""
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, validate_assignment=True)


# --------------------------------------------------------------------------- change set


class DiffLine(_Model):
    """One line inside a diff hunk, with its line number on each side."""

    kind: LineKind
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


class Hunk(_Model):
    """A contiguous block of changes (one ``@@ ... @@`` section of a unified diff)."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str = ""
    lines: list[DiffLine] = Field(default_factory=list)

    @property
    def new_end(self) -> int:
        """Last line number this hunk covers in the new file."""
        return self.new_start + max(self.new_count, 1) - 1


class FileChange(_Model):
    """Everything the diff says about one file."""

    path: str
    old_path: str | None = None
    change_type: ChangeType
    language: Language = Language.OTHER
    is_binary: bool = False
    hunks: list[Hunk] = Field(default_factory=list)

    @property
    def additions(self) -> int:
        """Number of added lines."""
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind is LineKind.ADDED)

    @property
    def deletions(self) -> int:
        """Number of removed lines."""
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind is LineKind.REMOVED)

    def added_lines(self) -> set[int]:
        """Line numbers (in the new file) of every added line."""
        return {
            ln.new_lineno
            for h in self.hunks
            for ln in h.lines
            if ln.kind is LineKind.ADDED and ln.new_lineno is not None
        }

    def changed_ranges(self) -> list[tuple[int, int]]:
        """Contiguous ranges of added lines in the new file."""
        return _to_ranges(sorted(self.added_lines()))

    def touches(self, start: int, end: int, slack: int = 0) -> bool:
        """True if [start, end] overlaps an added line (within ``slack`` lines)."""
        lo, hi = start - slack, end + slack
        return any(lo <= n <= hi for n in self.added_lines())

    def distance_to_change(self, line: int) -> int | None:
        """Lines between ``line`` and the nearest added line (None if nothing was added)."""
        added = self.added_lines()
        if not added:
            return None
        return min(abs(line - n) for n in added)


def _to_ranges(nums: Iterable[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for n in nums:
        if ranges and n == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], n)
        else:
            ranges.append((n, n))
    return ranges


class SkippedFile(_Model):
    """A file left out of the review, and why (binary, generated, sensitive ...)."""

    path: str
    reason: str


class ChangeSet(_Model):
    """The parsed diff under review: changed files plus the ones that were skipped."""

    source: str = "diff"
    base_ref: str | None = None
    head_ref: str | None = None
    baseline_ref: str | None = Field(default=None, description="Exact tree used for diagnostics")
    title: str | None = None
    files: list[FileChange] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)

    def get(self, path: str) -> FileChange | None:
        """The change for ``path``, or None if that file is not in the diff."""
        for f in self.files:
            if f.path == path:
                return f
        return None

    @property
    def lines_added(self) -> int:
        """Added lines across all files."""
        return sum(f.additions for f in self.files)

    @property
    def lines_removed(self) -> int:
        """Removed lines across all files."""
        return sum(f.deletions for f in self.files)

    def reviewable(self) -> Iterator[FileChange]:
        """Files that still exist after the change (deleted files cannot be reviewed)."""
        return (f for f in self.files if f.change_type is not ChangeType.DELETED)


# --------------------------------------------------------------------------- findings


class Evidence(_Model):
    """One piece of support for a finding: a quote, a tool message or a verifier note."""

    source: str = Field(description="Who produced this evidence: ai, ruff, verifier, graph ...")
    text: str
    file: str | None = None
    line: int | None = None


class CheckOutcome(StrEnum):
    """Result of one verification check."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    SKIPPED = "skipped"


class VerificationCheck(_Model):
    """One deterministic check the verifier ran on a finding, and what it found."""

    name: str
    outcome: CheckOutcome
    detail: str
    weight: float = 1.0
    decisive: bool = Field(
        default=False,
        description="A decisive contradiction rejects the finding regardless of other checks.",
    )


class VerificationResult(_Model):
    """The verifier's overall verdict on a finding, with every check it ran."""

    status: VerificationStatus
    score: float = Field(ge=-1.0, le=1.0)
    checks: list[VerificationCheck] = Field(default_factory=list)
    summary: str = ""
    reachability: str = Field(
        default="unknown", description="entrypoint | test-only | unreachable | unknown"
    )
    call_path: list[str] = Field(default_factory=list)


class PriorityScore(_Model):
    """Why a finding is ranked where it is: the factors that were multiplied together."""

    score: float
    severity_weight: float
    confidence: float
    reachability: float
    change_relevance: float
    explanation: str


class Finding(_Model):
    """A single review finding — the central object of the whole system (spec §13)."""

    id: str = Field(default_factory=lambda: new_id("F"))
    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    explanation: str = ""
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    evidence: list[Evidence] = Field(default_factory=list)
    suggested_fix: str | None = None
    source: FindingSource
    origins: list[str] = Field(
        default_factory=list, description="Detailed producers, e.g. ['ai:claude', 'ruff:S608']"
    )
    rule_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: FindingStatus = FindingStatus.OPEN
    fingerprint: str = ""
    verification: VerificationResult | None = None
    priority: PriorityScore | None = None
    in_changed_lines: bool = True
    baseline_status: str | None = Field(
        default=None, description="introduced | pre-existing | unknown after base/head comparison"
    )
    merged_ids: list[str] = Field(default_factory=list)
    suppressed_reason: str | None = None
    symbol: str | None = Field(default=None, description="Enclosing function/class, if known")
    site_anchor: str | None = Field(
        default=None, description="Normalized source site and occurrence within its symbol"
    )

    @property
    def location(self) -> str:
        """``file:line`` or ``file:start-end`` for display."""
        if self.line_end != self.line_start:
            return f"{self.file}:{self.line_start}-{self.line_end}"
        return f"{self.file}:{self.line_start}"

    @property
    def is_deterministic(self) -> bool:
        """True when no AI claim is involved: every producer is a deterministic tool."""
        return bool(self.origins) and all(not o.startswith("ai:") for o in self.origins)


# --------------------------------------------------------------------------- analysis runs


class ToolStatus(StrEnum):
    """Outcome of one static-analysis tool run (stored as plain text on ``AnalysisRun``)."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


# Tool outcomes that mean "the tool should have run but did not finish properly".
TOOL_PROBLEMS = frozenset({ToolStatus.FAILED, ToolStatus.TIMEOUT})


class AnalysisRun(_Model):
    """Record of one static-analysis tool run (for the UI and for debugging)."""

    tool: str
    status: str = Field(description="ok | unavailable | failed | timeout | skipped")
    duration_ms: int = 0
    findings: int = 0
    detail: str = ""


class StageRecord(_Model):
    """Timing and status of one pipeline stage; streamed to the UI as progress."""

    name: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    duration_ms: int | None = None
    detail: str = ""
    metrics: dict[str, float | int | str] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-readable stage name, e.g. 'Building code graph'."""
        return STAGE_LABELS[self.name]


class TokenUsage(_Model):
    """Tokens sent to and received from the AI provider."""

    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


# --------------------------------------------------------------------------- summary


class ReviewStats(_Model):
    """Counts shown in the review summary."""

    files_changed: int = 0
    files_reviewed: int = 0
    files_skipped: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_verification: dict[str, int] = Field(default_factory=dict)
    suppressed: int = 0


class ReviewSummary(_Model):
    """The short written summary at the top of a review (spec §18)."""

    risk: RiskLevel = RiskLevel.NONE
    headline: str = ""
    stats: ReviewStats = Field(default_factory=ReviewStats)
    what_changed: list[str] = Field(default_factory=list)
    attention: list[str] = Field(default_factory=list)
    verified: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)


class ReviewResult(_Model):
    """Everything a finished review produced. Saved to the database as-is."""

    review_id: str = Field(default_factory=lambda: new_id("R"))
    status: ReviewStatus = ReviewStatus.COMPLETED
    changeset: ChangeSet
    findings: list[Finding] = Field(default_factory=list, description="Surfaced findings")
    suppressed: list[Finding] = Field(
        default_factory=list, description="Rejected, below threshold, or over the display budget"
    )
    summary: ReviewSummary = Field(default_factory=ReviewSummary)
    stages: list[StageRecord] = Field(default_factory=list)
    analysis_runs: list[AnalysisRun] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    graph: dict[str, object] | None = Field(
        default=None, description="Serialized code-graph subgraph for the architecture view"
    )
    sources: dict[str, str] = Field(
        default_factory=dict, description="Snapshot of reviewed/context file contents (redacted)"
    )
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0

    def all_findings(self) -> list[Finding]:
        """Surfaced and suppressed findings together."""
        return [*self.findings, *self.suppressed]

    def find(self, finding_id: str) -> Finding | None:
        """Look a finding up by id, including ids that were merged into another finding."""
        for f in self.all_findings():
            if f.id == finding_id or finding_id in f.merged_ids:
                return f
        return None
