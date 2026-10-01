"""Builds the ``ReviewRequest`` sent to the AI provider.

Called by the orchestrator's AI-review stage. Everything the model sees is assembled
here: the (size-capped) diff, the context blocks chosen by the context engine, and a
short list of static-analysis hints. Secrets were already redacted by the filter stage.
"""

from __future__ import annotations

from sentinel.analysis.diff.parser import render_file_diff
from sentinel.analysis.graph.context import ContextBundle
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import ReviewRequest, StaticHint
from sentinel.core.domain.models import ChangeSet, ChangeType, Finding, Language

MAX_DIFF_CHARS = 120_000
MAX_STATIC_HINTS = 40
# Ask the model for at least this many candidates; the verifier and the display budget
# decide what is finally shown.
MIN_REQUESTED_FINDINGS = 10


def build_review_request(
    *,
    review_id: str,
    repository: str,
    changeset: ChangeSet,
    bundle: ContextBundle | None,
    static_findings: list[Finding],
    config: RepoConfig,
) -> ReviewRequest:
    """Assemble the provider request for one review."""
    languages = {f.language.value for f in changeset.files if f.language is not Language.OTHER}
    return ReviewRequest(
        review_id=review_id,
        repository=repository,
        title=changeset.title,
        diff=render_diff_for_prompt(changeset),
        changed_files=[f.path for f in changeset.files],
        context=bundle.blocks if bundle else [],
        static_findings=[static_hint(f) for f in static_findings[:MAX_STATIC_HINTS]],
        categories=config.review.enabled_categories(),
        max_findings=max(config.review.max_findings, MIN_REQUESTED_FINDINGS),
        languages=sorted(languages),
    )


def render_diff_for_prompt(changeset: ChangeSet) -> str:
    """The unified diff of every reviewable file, stopping at ``MAX_DIFF_CHARS``.

    Files past the budget are listed as omitted so the model knows they exist; deleted
    files are listed without content.
    """
    parts: list[str] = []
    used = 0
    for change in changeset.reviewable():
        text = render_file_diff(change)
        if used + len(text) > MAX_DIFF_CHARS:
            parts.append(f"--- {change.path}: diff omitted (size budget reached)")
            continue
        used += len(text)
        parts.append(text)
    for change in changeset.files:
        if change.change_type is ChangeType.DELETED:
            parts.append(f"--- a/{change.path}\n+++ /dev/null\n(file deleted)")
    return "\n".join(parts)


def static_hint(finding: Finding) -> StaticHint:
    """A deterministic finding in the short form given to the model as a hint."""
    tool = finding.origins[0].split(":")[0] if finding.origins else "static"
    return StaticHint(
        tool=tool,
        rule=finding.rule_id,
        file=finding.file,
        line=finding.line_start,
        message=finding.title,
    )
