"""Provide bounded historical review context without expanding editable file scope.

The fix service supplies its saved ChangeSet to the engine. This helper filters it
again and keeps only files in the current allowed context, so removed contracts can
inform a fix without sending sensitive/ignored files or authorizing extra edits.
"""

from collections.abc import Collection

from sentinel.analysis.diff.filtering import filter_changeset
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import ChangeSet
from sentinel.core.review.ai_request import render_diff_for_prompt

MAX_FIX_DIFF_CHARS = 16_000
TRUNCATED_NOTE = "\n[Original review diff truncated to the fix-context budget]"


def reviewed_fix_diff(
    changeset: ChangeSet | None, allowed: Collection[str], config: RepoConfig
) -> str:
    """Return redacted history of allowed files, never a new edit permission."""
    if changeset is None:
        return ""
    filtered = filter_changeset(
        changeset, ignore=config.ignore, languages=config.languages
    ).changeset
    scoped = filtered.model_copy(
        update={"files": [change for change in filtered.files if change.path in allowed]}
    )
    text = render_diff_for_prompt(scoped)
    if len(text) <= MAX_FIX_DIFF_CHARS:
        return text
    return text[: MAX_FIX_DIFF_CHARS - len(TRUNCATED_NOTE)] + TRUNCATED_NOTE


def reviewed_fix_config(changeset: ChangeSet | None, config: RepoConfig) -> RepoConfig:
    """Carry excluded review paths into fix source selection without editing saved config."""
    if changeset is None:
        return config
    filtered = filter_changeset(changeset, ignore=config.ignore, languages=config.languages)
    ignored = list(
        dict.fromkeys([*config.ignore, *(item.path for item in filtered.changeset.skipped)])
    )
    return config.model_copy(update={"ignore": ignored})
