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
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}[self]

    def at_least(self, other: Severity) -> bool:
        return self.rank >= other.rank


class Category(StrEnum):
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
    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    FIXED = "fixed"


class VerificationStatus(StrEnum):
    SUPPORTED = "supported"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class Language(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    OTHER = "other"


class LineKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CONTEXT = "context"


class RiskLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class StageName(StrEnum):
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
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, validate_assignment=True)


# --------------------------------------------------------------------------- change set


class DiffLine(_Model):
    kind: LineKind
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


class Hunk(_Model):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str = ""
    lines: list[DiffLine] = Field(default_factory=list)

    @property
    def new_end(self) -> int:
        return self.new_start + max(self.new_count, 1) - 1


class FileChange(_Model):
    path: str
    old_path: str | None = None
    change_type: ChangeType
    language: Language = Language.OTHER
    is_binary: bool = False
    hunks: list[Hunk] = Field(default_factory=list)

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind is LineKind.ADDED)

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind is LineKind.REMOVED)

    def added_lines(self) -> set[int]:
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
    path: str
    reason: str


class ChangeSet(_Model):
    source: str = "diff"
    base_ref: str | None = None
    head_ref: str | None = None
    title: str | None = None
    files: list[FileChange] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)

    def get(self, path: str) -> FileChange | None:
        for f in self.files:
            if f.path == path:
                return f
        return None

    @property
    def lines_added(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def lines_removed(self) -> int:
        return sum(f.deletions for f in self.files)

    def reviewable(self) -> Iterator[FileChange]:
        return (f for f in self.files if f.change_type is not ChangeType.DELETED)


# --------------------------------------------------------------------------- findings


class Evidence(_Model):
    source: str = Field(description="Who produced this evidence: ai, ruff, verifier, graph ...")
    text: str
    file: str | None = None
    line: int | None = None


class CheckOutcome(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    SKIPPED = "skipped"


class VerificationCheck(_Model):
    name: str
    outcome: CheckOutcome
    detail: str
    weight: float = 1.0
    decisive: bool = Field(
        default=False,
        description="A decisive contradiction rejects the finding regardless of other checks.",
    )


class VerificationResult(_Model):
    status: VerificationStatus
    score: float = Field(ge=-1.0, le=1.0)
    checks: list[VerificationCheck] = Field(default_factory=list)
    summary: str = ""
    reachability: str = Field(
        default="unknown", description="entrypoint | test-only | unreachable | unknown"
    )
    call_path: list[str] = Field(default_factory=list)


class PriorityScore(_Model):
    score: float
    severity_weight: float
    confidence: float
    reachability: float
    change_relevance: float
    explanation: str


class Finding(_Model):
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
    merged_ids: list[str] = Field(default_factory=list)
    suppressed_reason: str | None = None
    symbol: str | None = Field(default=None, description="Enclosing function/class, if known")

    @property
    def location(self) -> str:
        if self.line_end != self.line_start:
            return f"{self.file}:{self.line_start}-{self.line_end}"
        return f"{self.file}:{self.line_start}"

    @property
    def is_deterministic(self) -> bool:
        """True when no AI claim is involved: every producer is a deterministic tool."""
        return bool(self.origins) and all(not o.startswith("ai:") for o in self.origins)


# --------------------------------------------------------------------------- analysis runs


class AnalysisRun(_Model):
    tool: str
    status: str = Field(description="ok | unavailable | failed | timeout | skipped")
    duration_ms: int = 0
    findings: int = 0
    detail: str = ""


class StageRecord(_Model):
    name: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    duration_ms: int | None = None
    detail: str = ""
    metrics: dict[str, float | int | str] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        return STAGE_LABELS[self.name]


class TokenUsage(_Model):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


# --------------------------------------------------------------------------- summary


class ReviewStats(_Model):
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
    risk: RiskLevel = RiskLevel.NONE
    headline: str = ""
    stats: ReviewStats = Field(default_factory=ReviewStats)
    what_changed: list[str] = Field(default_factory=list)
    attention: list[str] = Field(default_factory=list)
    verified: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)


class ReviewResult(_Model):
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
        return [*self.findings, *self.suppressed]

    def find(self, finding_id: str) -> Finding | None:
        for f in self.all_findings():
            if f.id == finding_id or finding_id in f.merged_ids:
                return f
        return None
