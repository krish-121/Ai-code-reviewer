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
    export_index,
    export_tree,
    head_sha,
    is_git_repo,
    path_changeset,
    range_changeset,
    repo_root,
    rev_parse,
    staged_changeset,
    unstaged_paths,
    worktree_changeset,
)
from sentinel.core.domain.models import ChangeSet


class LocalRequest(BaseModel):
    """What to review in a local repository: a mode plus refs or a sub-path."""

    kind: str = "local"
    path: str
    mode: str = Field(default="staged", pattern="^(staged|worktree|range|path)$")
    base: str | None = None
    head: str | None = None
    subpath: str | None = None


@dataclass
class PreparedWorkspace:
    """The change to review and a directory holding the matching code."""

    changeset: ChangeSet
    workspace: Path
    repo_root: Path
    repository: str


@contextmanager
def prepare_local(request: LocalRequest) -> Iterator[PreparedWorkspace]:
    """Yield the change set and a workspace for a local review; temporary trees are removed.

    Modes: ``staged``, ``worktree``, ``range`` (base...head) and ``path`` (every file under a
    folder, reviewed as newly added).
    """
    root = repo_root(Path(request.path).expanduser().resolve())
    tmp: Path | None = None
    try:
        if request.mode == "path":
            sub = (root / request.subpath).resolve() if request.subpath else None
            changeset = path_changeset(root, sub)
            workspace = root
        elif not is_git_repo(root):
            raise GitError(f"{root} is not a git repository (use mode 'path' to review files)")
        elif request.mode == "staged":
            changeset = staged_changeset(root)
            changed = {f.path for f in changeset.files}
            if changed & unstaged_paths(root):
                tmp = Path(tempfile.mkdtemp(prefix="sentinel-index-"))
                export_index(root, tmp)
                workspace = tmp
            else:
                workspace = root
        elif request.mode == "worktree":
            changeset = worktree_changeset(root)
            workspace = root
        else:
            base = request.base or "HEAD~1"
            head = request.head or "HEAD"
            changeset = range_changeset(root, base, head)
            current = head_sha(root)
            if rev_parse(root, head) == current and not unstaged_paths(root):
                workspace = root
            else:
                tmp = Path(tempfile.mkdtemp(prefix="sentinel-tree-"))
                export_tree(root, head, tmp)
                workspace = tmp
        yield PreparedWorkspace(changeset, workspace, root, root.name)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
