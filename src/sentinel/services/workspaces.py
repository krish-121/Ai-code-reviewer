"""Turn a review request into (change set, workspace directory).

The *workspace* is a directory whose contents equal the new version of the code, so
static tools and the code graph see exactly what is being reviewed. For staged reviews
with further unstaged edits, or for ranges whose head isn't checked out, the right tree
is exported to a temporary directory instead of analyzing the working copy.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from sentinel.analysis.diff.git import (
    GitError,
    export_tree,
    is_git_repo,
    path_changeset,
    range_changeset,
    repo_root,
    rev_parse,
    snapshot_index,
    worktree_changeset,
)
from sentinel.core.domain.models import ChangeSet
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.core.review.baseline import needs_comparison


class LocalRequest(BaseModel):
    """What to review in a local repository: a mode plus refs or a sub-path."""

    kind: str = "local"
    path: str
    mode: str = Field(default="staged", pattern="^(staged|worktree|range|path)$")
    base: str | None = None
    head: str | None = None
    subpath: str | None = None
    allowed_roots: list[str] | None = None


@dataclass
class PreparedWorkspace:
    """The change to review and a directory holding the matching code."""

    changeset: ChangeSet
    workspace: Path
    repo_root: Path
    repository: str
    baseline: Path | None = None
    baseline_error: str | None = None


@contextmanager
def prepare_local(request: LocalRequest) -> Iterator[PreparedWorkspace]:
    """Yield the change set and a workspace for a local review; temporary trees are removed.

    Modes: ``staged``, ``worktree``, ``range`` (base...head) and ``path`` (every file under a
    folder, reviewed as newly added).
    """
    root = repo_root(Path(request.path).expanduser().resolve())
    if request.allowed_roots is not None:
        authorize_root(root, [Path(p) for p in request.allowed_roots])
    tmp: Path | None = None
    try:
        if request.mode == "path":
            sub = (root / request.subpath).resolve() if request.subpath else None
            changeset = path_changeset(root, sub)
            workspace = root
        elif not is_git_repo(root):
            raise GitError(f"{root} is not a git repository (use mode 'path' to review files)")
        elif request.mode == "staged":
            tmp = Path(tempfile.mkdtemp(prefix="sentinel-index-"))
            changeset = snapshot_index(root, tmp)
            workspace = tmp
        elif request.mode == "worktree":
            changeset = worktree_changeset(root)
            tmp = scratch_copy(root, prefix="sentinel-worktree-")
            if worktree_changeset(root) != changeset:
                raise GitError("working-tree diff changed while taking its snapshot; retry review")
            workspace = tmp
        else:
            base = request.base or "HEAD~1"
            head = rev_parse(root, request.head or "HEAD")
            base = rev_parse(root, base)
            changeset = range_changeset(root, base, head)
            tmp = Path(tempfile.mkdtemp(prefix="sentinel-tree-"))
            export_tree(root, head, tmp)
            workspace = tmp
        with prepare_baseline(root, changeset) as (baseline, error):
            yield PreparedWorkspace(changeset, workspace, root, root.name, baseline, error)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


@contextmanager
def prepare_baseline(root: Path, changeset: ChangeSet) -> Iterator[tuple[Path | None, str | None]]:
    """Export the diff's immutable old tree; report acquisition failures as incomplete."""
    if not needs_comparison(changeset):
        yield None, None
        return
    with tempfile.TemporaryDirectory(prefix="sentinel-base-") as directory:
        baseline = Path(directory)
        try:
            if not changeset.base_ref:
                raise GitError("the diff has no base revision")
            export_tree(root, changeset.base_ref, baseline)
            changeset.baseline_ref = changeset.base_ref
        except (GitError, OSError) as exc:
            yield None, f"base snapshot unavailable: {exc}"
        else:
            yield baseline, None


def authorize_root(path: Path, allowed: list[Path]) -> Path:
    """Authorize the effective Git root, including when a queued request executes later."""
    root = repo_root(path.resolve()).resolve()
    if not any(root.is_relative_to(item.resolve()) for item in allowed):
        raise GitError("effective repository root is outside the allowed directories")
    return root
