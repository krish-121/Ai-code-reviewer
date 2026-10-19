"""Renaming a protected file must not expose its old diff or future fix context."""

from pathlib import Path

import pytest

from sentinel.analysis.diff.filtering import filter_changeset
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import ChangeSet
from sentinel.core.fixes.context import fix_context
from sentinel.core.fixes.review_context import reviewed_fix_config, reviewed_fix_diff
from tests.unit.test_verification import finding


def renamed(old_path: str) -> ChangeSet:
    return parse_unified_diff(
        f"diff --git a/{old_path} b/settings.py\nsimilarity index 90%\n"
        f"rename from {old_path}\nrename to settings.py\n"
        f"--- a/{old_path}\n+++ b/settings.py\n@@ -1 +1 @@\n"
        "-private_setting = 'old-private-value'\n+private_setting = 'new-private-value'\n"
    )


@pytest.mark.parametrize(
    "old_path", [".env", "private.pem", "private/settings.py", "vendor/settings.py"]
)
def test_protected_rename_paths_are_excluded_from_review_and_fix_history(old_path: str) -> None:
    changeset = renamed(old_path)
    config = RepoConfig(ignore=["private/**"])
    result = filter_changeset(changeset, ignore=config.ignore)
    assert not result.changeset.files
    assert result.changeset.skipped[0].path == "settings.py"
    assert reviewed_fix_diff(changeset, ["settings.py"], config) == ""
    effective = reviewed_fix_config(changeset, config)
    assert "settings.py" in effective.ignore and config.ignore == ["private/**"]


def test_public_rename_remains_reviewable() -> None:
    changeset = renamed("public.py")
    result = filter_changeset(changeset)
    assert len(result.changeset.files) == 1
    assert "old-private-value" in reviewed_fix_diff(changeset, ["settings.py"], RepoConfig())


def test_skipped_rename_is_not_reintroduced_as_a_related_fix_file(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        "from settings import private_setting\nvalue = private_setting\n"
    )
    (tmp_path / "settings.py").write_text("private_setting = 'new-private-value'\n")
    config = RepoConfig()
    effective = reviewed_fix_config(renamed(".env"), config)
    context = fix_context(tmp_path, finding(file="service.py", line_start=2, line_end=2), effective)
    assert "settings.py" not in context.files
    assert all("new-private-value" not in content for content in context.files.values())
    assert reviewed_fix_config(None, config) is config
