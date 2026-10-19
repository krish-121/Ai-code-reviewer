"""The contract between the review engine and any AI provider.

The model must answer with JSON matching ``AIReviewPayload`` / ``AIFixPayload``. These
are strict Pydantic models (unknown fields are rejected), so a response is either a
valid, typed object or an error the provider layer retries once with a correction.
Free-form Markdown is never parsed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel.core.domain.models import Category, Severity, TokenUsage


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AIFinding(_Strict):
    """One finding exactly as the model must return it."""

    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=3, max_length=200)
    explanation: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    suggested_fix: str | None = Field(default=None, max_length=4000)

    @field_validator("category", "severity", mode="before")
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v


class AIReviewPayload(_Strict):
    """The complete JSON object the model returns for a review."""

    findings: list[AIFinding] = Field(max_length=50)


class FileEdit(_Strict):
    """A search/replace edit the model proposes for a fix."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    file: str = Field(min_length=1)
    search: str = Field(description="Replace: exact text occurring once. Create: empty string.")
    replace: str
    operation: Literal["replace", "create"] = "replace"


class AIFixPayload(_Strict):
    """The complete JSON object the model returns for a fix."""

    summary: str = Field(min_length=1, max_length=2000)
    edits: list[FileEdit] = Field(min_length=1, max_length=10)


# --------------------------------------------------------------------------- requests


class ContextBlock(BaseModel):
    """A piece of repository source given to the model as *data*."""

    kind: str = Field(description="changed | caller | callee | test | import | endpoint | config")
    file: str
    symbol: str | None = None
    line_start: int
    line_end: int
    code: str
    reason: str = ""


class StaticHint(BaseModel):
    """A static-analysis result passed to the model as a hint."""

    tool: str
    rule: str | None = None
    file: str
    line: int
    message: str


class ReviewRequest(BaseModel):
    """Everything a provider needs to review a change. Built by the orchestrator."""

    review_id: str
    repository: str
    title: str | None = None
    diff: str
    changed_files: list[str]
    context: list[ContextBlock] = Field(default_factory=list)
    static_findings: list[StaticHint] = Field(default_factory=list)
    categories: list[Category]
    max_findings: int = 15
    languages: list[str] = Field(default_factory=list)


class FixRequest(BaseModel):
    """Everything a provider needs to propose a fix for one finding."""

    finding_title: str
    finding_explanation: str
    category: Category
    file: str
    line_start: int
    line_end: int
    suggested_fix: str | None = None
    files: dict[str, str] = Field(description="path -> full current content of relevant files")
    allowed_new_files: list[str] = Field(
        default_factory=list, description="Only these absent regression-test files may be created"
    )
    review_diff: str = Field(
        default="", description="Filtered original change; historical context only"
    )
    feedback: str | None = Field(
        default=None, description="Validation failures from a previous attempt, if retrying"
    )


class AIReviewResult(BaseModel):
    """A validated review payload plus usage and provider metadata."""

    payload: AIReviewPayload
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str
    provider: str
    attempts: int = 1
    cached: bool = False
    fallback_events: list[str] = Field(default_factory=list)


class AIFixResult(BaseModel):
    """A validated fix payload plus usage and provider metadata."""

    payload: AIFixPayload
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str
    provider: str
    attempts: int = 1
    fallback_events: list[str] = Field(default_factory=list)
