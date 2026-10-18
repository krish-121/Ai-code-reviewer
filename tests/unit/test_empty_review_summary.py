"""An empty snapshot must not look like a successfully assessed clean change."""

import pytest

from sentinel.core.domain.models import ChangeSet, SkippedFile
from sentinel.core.review.summary import build_summary


@pytest.mark.parametrize("filtered", [False, True])
def test_no_assessed_code_is_explicit_in_summary(filtered: bool) -> None:
    changeset = ChangeSet(source="staged")
    if filtered:
        changeset.skipped = [SkippedFile(path="generated.js", reason="generated")]
    summary = build_summary(changeset, [], [], changed_symbols=[], runs=[], limitations=[])
    assert "no code was assessed" in summary.headline
    assert "No problems found" not in summary.headline
    assert summary.stats.files_reviewed == 0
