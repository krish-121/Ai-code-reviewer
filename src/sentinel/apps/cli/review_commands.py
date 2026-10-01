"""``sentinel review``: review staged/uncommitted changes, a commit range, a path or a PR.

Flow: build a ``LocalRequest`` (or fetch the PR) -> ``ReviewService.create_*`` ->
``ReviewService.run`` with a live progress display -> print the result
(``render.py``, JSON, or the GitHub-comment Markdown).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from sentinel.analysis.diff.git import is_git_repo, repo_root
from sentinel.apps.cli.common import (
    EXIT_FAILED,
    EXIT_FINDINGS,
    ai_factory_for,
    console,
    fail,
    load_cli_settings,
    open_database,
)
from sentinel.apps.cli.render import LiveProgress, render_review
from sentinel.bootstrap import github_factory
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import ReviewResult, ReviewStatus, Severity
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import LOCAL_USER_ID
from sentinel.integrations.github.render import summary_comment
from sentinel.integrations.github.webhooks import PullRequestEvent
from sentinel.services.reviews import ReviewService
from sentinel.services.workspaces import LocalRequest

ORIGIN_RE = re.compile(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$")
DEFAULT_RANGE_BASE, DEFAULT_RANGE_HEAD = "HEAD~1", "HEAD"
RICH, JSON, MARKDOWN = "rich", "json", "markdown"


def review(
    target: Annotated[Path | None, typer.Argument(help="Review all files under this path.")] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Review staged changes.")] = False,
    worktree: Annotated[
        bool, typer.Option("--worktree", help="Review uncommitted changes.")
    ] = False,
    path: Annotated[
        Path | None, typer.Option("--path", help="Review all files under a path.")
    ] = None,
    range_: Annotated[str | None, typer.Option("--range", help="Review BASE..HEAD.")] = None,
    pr: Annotated[int | None, typer.Option("--pr", help="Review a GitHub pull request.")] = None,
    repo: Annotated[
        str | None, typer.Option("--repo", help="owner/name for --pr (default: origin).")
    ] = None,
    provider: Annotated[str | None, typer.Option(help="claude | gemini | ollama | none")] = None,
    model: Annotated[str | None, typer.Option(help="Model name for the provider.")] = None,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Deterministic analysis only.")] = False,
    output: Annotated[str, typer.Option("--format", help="rich | json | markdown")] = RICH,
    fail_on: Annotated[
        str, typer.Option(help="Exit 1 if a finding reaches this severity: high|medium|low|none")
    ] = "none",
    verbose: Annotated[
        bool, typer.Option("--details", "-d", help="Show evidence and verification checks.")
    ] = False,
    show_suppressed: Annotated[
        bool, typer.Option("--show-suppressed", help="List suppressed findings.")
    ] = False,
) -> None:
    """Review a change: staged/uncommitted changes, a commit range, a path, or a PR."""
    settings = load_cli_settings(provider=provider, model=model)
    if no_ai:
        settings = settings.model_copy(update={"provider": "none"})
    db = open_database(settings)
    if pr is not None:
        result = _review_pull_request(db, settings, pr, repo, no_ai)
    else:
        request = _local_request(target, staged, worktree, path, range_)
        result = _review_local(db, settings, request, no_ai, live=output == RICH)
    _print_result(result, output, verbose, show_suppressed)
    if result.status is ReviewStatus.FAILED:
        raise typer.Exit(EXIT_FAILED)
    if _reaches_threshold(result, fail_on):
        raise typer.Exit(EXIT_FINDINGS)


def _review_local(
    db: Database, settings: Settings, request: LocalRequest, no_ai: bool, *, live: bool
) -> ReviewResult:
    service = ReviewService(db, settings, ai_factory=ai_factory_for(no_ai))
    review_id = service.create_local(LOCAL_USER_ID, request, enqueue=False)
    try:
        if not live:
            return service.run(review_id)
        with LiveProgress(console) as progress:
            return service.run(review_id, progress)
    except SentinelError as exc:
        raise fail(str(exc)) from exc


def _local_request(
    target: Path | None, staged: bool, worktree: bool, path: Path | None, range_: str | None
) -> LocalRequest:
    """Translate the command-line options into what to review."""
    chosen = path or target
    if chosen is not None:
        root = repo_root(chosen.resolve())
        sub = chosen.resolve()
        rel = str(sub.relative_to(root)) if sub != root and sub.is_relative_to(root) else None
        return LocalRequest(path=str(root), mode="path", subpath=rel)
    cwd = Path.cwd()
    if range_:
        base, _, head = range_.replace("...", "..").partition("..")
        return LocalRequest(
            path=str(cwd),
            mode="range",
            base=base or DEFAULT_RANGE_BASE,
            head=head or DEFAULT_RANGE_HEAD,
        )
    if not is_git_repo(cwd):
        raise fail("not inside a git repository; pass a path to review files directly")
    if staged or worktree:
        return LocalRequest(path=str(cwd), mode="staged" if staged else "worktree")
    # Neither flag: review what is staged, or everything uncommitted if nothing is.
    return LocalRequest(path=str(cwd), mode="staged" if _has_staged_changes(cwd) else "worktree")


def _has_staged_changes(cwd: Path) -> bool:
    quiet_diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=cwd, check=False)
    return quiet_diff.returncode != 0


def _origin_repo() -> str | None:
    """``owner/name`` of the ``origin`` remote when it points at GitHub."""
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False
    )
    match = ORIGIN_RE.search(proc.stdout.strip())
    return match.group(1) if match else None


def _review_pull_request(
    db: Database, settings: Settings, number: int, repo: str | None, no_ai: bool
) -> ReviewResult:
    """Review a GitHub PR from the command line (token auth; nothing is posted)."""
    factory = github_factory(settings)
    if factory is None:
        raise fail("GitHub token not configured. Set SENTINEL_GITHUB_TOKEN (or GITHUB_TOKEN).")
    full_name = repo or _origin_repo()
    if not full_name:
        raise fail("cannot infer the GitHub repository; pass --repo owner/name")
    data = factory(None).pull(full_name, number)
    event = PullRequestEvent(
        action="cli",
        repo=full_name,
        number=number,
        title=str(data.get("title", "")),
        author=(data.get("user") or {}).get("login"),
        url=data.get("html_url"),
        head_sha=str((data.get("head") or {}).get("sha", "")),
        base_sha=(data.get("base") or {}).get("sha"),
        installation_id=None,
        draft=False,
    )
    service = ReviewService(db, settings, ai_factory=ai_factory_for(no_ai), github_factory=factory)
    review_id = service.create_github(event, enqueue=False, publish=False)
    with LiveProgress(console) as progress:
        return service.run(review_id, progress)


def _print_result(result: ReviewResult, output: str, verbose: bool, show_suppressed: bool) -> None:
    if output == JSON:
        data = result.model_dump(mode="json", exclude={"sources", "graph"})
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    elif output == MARKDOWN:
        sys.stdout.write(summary_comment(result) + "\n")
    else:
        render_review(console, result, verbose=verbose, show_suppressed=show_suppressed)


def _reaches_threshold(result: ReviewResult, fail_on: str) -> bool:
    """True when ``--fail-on`` names a severity and a surfaced finding is at least that bad."""
    try:
        threshold = Severity(fail_on.lower())
    except ValueError:  # "none" or anything else disables the check
        return False
    return any(f.severity.at_least(threshold) for f in result.findings)
