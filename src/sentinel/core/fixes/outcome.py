"""The result of trying to fix a finding: the patch and every check it went through.

Produced by ``FixEngine`` (``engine.py``), stored on ``FixAttempt`` rows by
``services/fixes.py``, and shown by the CLI and the web UI's fix panel.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from sentinel.core.domain.ai import FileEdit

CheckStatus = Literal["passed", "failed", "skipped", "error"]
FixStatus = Literal["validated", "unverified", "failed", "error"]


class FixCheck(BaseModel):
    """One validation step (apply, syntax, finding-resolved, no-new-issues, tests)."""

    name: str
    status: CheckStatus
    detail: str = ""
    duration_ms: int = 0


class FixOutcome(BaseModel):
    """A proposed fix and its verdict.

    ``validated``: a deterministic re-check or the tests confirm the fix.
    ``unverified``: nothing failed, but nothing could confirm it either.
    ``failed``: a check failed. ``error``: no patch could be produced.
    """

    status: FixStatus
    summary: str = ""
    patch: str = ""
    edits: list[FileEdit] = Field(default_factory=list)
    original_hashes: dict[str, str] = Field(default_factory=dict)
    checks: list[FixCheck] = Field(default_factory=list)
    attempts: int = 0
    isolation: str = "none"
    error: str | None = None
    provider: str | None = None
    model: str | None = None

    @property
    def ok(self) -> bool:
        """True when the fix was validated."""
        return self.status == "validated"
