"""Acquire immutable GitHub baseline snapshots without hiding acquisition failures."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from sentinel.core.domain.models import ChangeSet
from sentinel.core.review.baseline import needs_comparison
from sentinel.integrations.github.client import GitHubClient, GitHubError


@contextmanager
def github_baseline(
    client: GitHubClient, repo: str, changeset: ChangeSet
) -> Iterator[tuple[Path | None, str | None]]:
    """Keep the base tree alive through review; a missing base yields a partial review."""
    if not needs_comparison(changeset):
        yield None, None
        return
    with TemporaryDirectory(prefix="sentinel-pr-base-") as directory:
        baseline = Path(directory)
        try:
            if not changeset.base_ref or not changeset.head_ref:
                raise GitHubError("PR revision metadata is incomplete")
            ancestor = client.merge_base(repo, changeset.base_ref, changeset.head_ref)
            client.download_tree(repo, ancestor, baseline)
            changeset.baseline_ref = ancestor
        except (GitHubError, OSError) as exc:
            yield None, f"GitHub base snapshot unavailable: {exc}"
        else:
            yield baseline, None
