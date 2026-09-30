"""`sentinel` command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from sentinel import __version__
from sentinel.analysis.diff.git import GitError, is_git_repo, repo_root
from sentinel.bootstrap import build_fix_engine, github_factory
from sentinel.core.configuration.config import (
    SECRET_KEYS,
    ConfigError,
    Settings,
    load_repo_config,
    load_settings,
    save_user_setting,
    user_config_path,
)
from sentinel.core.domain.models import FindingStatus, ReviewResult, ReviewStatus
from sentinel.core.domain.ports import AIConfigurationError, AIError
from sentinel.core.fixes.engine import ApplyError, apply_fix
from sentinel.infrastructure.database.models import Review
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import LOCAL_USER_ID, Store
from sentinel.infrastructure.observability.logging import configure_logging
from sentinel.integrations.github.render import summary_comment
from sentinel.integrations.github.webhooks import PullRequestEvent
from sentinel.services.reviews import ReviewService
from sentinel.services.workspaces import LocalRequest

from .render import LiveProgress, findings_table, render_finding, render_review

app = typer.Typer(
    name="sentinel",
    help="Context-aware AI code review & verification.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Show or change settings.", no_args_is_help=False)
users_app = typer.Typer(help="Manage API users (token auth mode).", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(users_app, name="users")

console = Console()
err = Console(stderr=True)

EXIT_FINDINGS, EXIT_CONFIG, EXIT_FAILED = 1, 2, 3
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

REPO_CONFIG_TEMPLATE = """\
# Sentinel review configuration — https://github.com/<you>/sentinel
review:
  categories: [bug, security, performance, tests, architecture]
  include_style: false        # style remarks are opt-in
  max_findings: 10            # show at most this many; the rest are listed as suppressed
  min_confidence: 0.3
severity_threshold: low       # low | medium | high
ignore:
  - generated/
  - migrations/
languages: [python, typescript, javascript]
static:
  disabled: []                # e.g. [mypy]
fix:
  test_command: null          # e.g. [python, -m, pytest, -q]; auto-detected when null
"""


def _fail(message: str, code: int = EXIT_CONFIG) -> typer.Exit:
    err.print(f"[bold red]ERROR:[/] {escape(message)}")
    return typer.Exit(code)


def _settings(**overrides: Any) -> Settings:
    try:
        return load_settings(overrides=overrides)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc


def _db(settings: Settings) -> Database:
    db = Database(settings.database_url)
    db.create_all()
    return db


def _ai_factory(no_ai: bool) -> Any:
    return (lambda: None) if no_ai else (lambda: "auto")


def version_callback(value: bool) -> None:
    if value:
        console.print(f"sentinel {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    import logging

    configure_logging("text", logging.DEBUG if verbose else logging.WARNING)


# --------------------------------------------------------------------------- review


@app.command()
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
    output: Annotated[str, typer.Option("--format", help="rich | json | markdown")] = "rich",
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
    settings = _settings(provider=provider, model=model)
    if no_ai:
        settings = settings.model_copy(update={"provider": "none"})
    db = _db(settings)
    if pr is not None:
        result = _review_pr(db, settings, pr, repo, no_ai)
    else:
        request = _local_request(target, staged, worktree, path, range_)
        service = ReviewService(db, settings, ai_factory=_ai_factory(no_ai))
        review_id = service.create_local(LOCAL_USER_ID, request, enqueue=False)
        quiet = output != "rich"
        try:
            if quiet:
                result = service.run(review_id)
            else:
                with LiveProgress(console) as progress:
                    result = service.run(review_id, progress)
        except AIConfigurationError as exc:
            raise _fail(str(exc)) from exc
        except GitError as exc:
            raise _fail(str(exc)) from exc
    _emit(result, output, verbose, show_suppressed)
    if result.status is ReviewStatus.FAILED:
        raise typer.Exit(EXIT_FAILED)
    threshold = SEVERITY_RANK.get(fail_on.lower())
    if threshold and any(SEVERITY_RANK[f.severity.value] >= threshold for f in result.findings):
        raise typer.Exit(EXIT_FINDINGS)


def _local_request(
    target: Path | None, staged: bool, worktree: bool, path: Path | None, range_: str | None
) -> LocalRequest:
    chosen = path or target
    if chosen is not None:
        root = repo_root(chosen.resolve())
        sub = chosen.resolve()
        rel = str(sub.relative_to(root)) if sub != root and sub.is_relative_to(root) else None
        return LocalRequest(path=str(root), mode="path", subpath=rel)
    cwd = Path.cwd()
    if range_:
        base, _, head = range_.replace("...", "..").partition("..")
        return LocalRequest(path=str(cwd), mode="range", base=base or "HEAD~1", head=head or "HEAD")
    if not is_git_repo(cwd):
        raise _fail("not inside a git repository; pass a path to review files directly")
    if staged:
        return LocalRequest(path=str(cwd), mode="staged")
    if worktree:
        return LocalRequest(path=str(cwd), mode="worktree")
    import subprocess

    has_staged = (
        subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=cwd, check=False).returncode != 0
    )
    return LocalRequest(path=str(cwd), mode="staged" if has_staged else "worktree")


def _origin_repo() -> str | None:
    import re
    import subprocess

    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False
    )
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", proc.stdout.strip())
    return m.group(1) if m else None


def _review_pr(
    db: Database, settings: Settings, number: int, repo: str | None, no_ai: bool
) -> ReviewResult:
    factory = github_factory(settings)
    if factory is None:
        raise _fail("GitHub token not configured. Set SENTINEL_GITHUB_TOKEN (or GITHUB_TOKEN).")
    full_name = repo or _origin_repo()
    if not full_name:
        raise _fail("cannot infer the GitHub repository; pass --repo owner/name")
    client = factory(None)
    data = client.pull(full_name, number)
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
    service = ReviewService(db, settings, ai_factory=_ai_factory(no_ai), github_factory=factory)
    review_id = service.create_github(event)
    with LiveProgress(console) as progress:
        return service.run(review_id, progress)


def _emit(result: ReviewResult, output: str, verbose: bool, show_suppressed: bool) -> None:
    if output == "json":
        data = result.model_dump(mode="json", exclude={"sources", "graph"})
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    elif output == "markdown":
        sys.stdout.write(summary_comment(result) + "\n")
    else:
        render_review(console, result, verbose=verbose, show_suppressed=show_suppressed)


# --------------------------------------------------------------------------- history & findings


def _load(store: Store, review_id: str | None) -> tuple[Review, ReviewResult]:
    user = store.local_user()
    row = store.review_for(user, review_id) if review_id else store.latest_review(user)
    if row is None:
        raise _fail("no review found; run `sentinel review` first", 1)
    return row, store.load_result(row)


@app.command()
def reviews(limit: Annotated[int, typer.Option(help="How many to show.")] = 15) -> None:
    """List past reviews."""
    settings = _settings()
    with _db(settings).transaction() as s:
        store = Store(s)
        rows = store.list_reviews(store.local_user(), limit=limit)
        table = Table(header_style="bold")
        for col in ("ID", "When", "Title", "Status", "Risk", "High", "Med", "Low"):
            table.add_column(col)
        for r in rows:
            counts = ((r.summary or {}).get("stats") or {}).get("by_severity", {})
            table.add_row(
                r.id,
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                escape(r.title or ""),
                r.status,
                r.risk or "-",
                str(counts.get("high", 0)),
                str(counts.get("medium", 0)),
                str(counts.get("low", 0)),
            )
        console.print(table)


@app.command()
def findings(
    review_id: Annotated[
        str | None, typer.Option("--review", help="Review ID (default: latest).")
    ] = None,
    show_all: Annotated[bool, typer.Option("--all", help="Include suppressed findings.")] = False,
) -> None:
    """List findings of a review."""
    settings = _settings()
    with _db(settings).transaction() as s:
        row, result = _load(Store(s), review_id)
        console.print(findings_table(result.findings, f"{row.id} — {row.title}"))
        if show_all and result.suppressed:
            console.print(findings_table(result.suppressed, "Suppressed"))


@app.command()
def show(finding_id: Annotated[str, typer.Argument(help="Finding ID, e.g. F-3fa9c2d1e0")]) -> None:
    """Show one finding with its evidence and verification checks."""
    settings = _settings()
    with _db(settings).transaction() as s:
        store = Store(s)
        row = store.finding_for(store.local_user(), finding_id)
        if row is None:
            raise _fail(f"finding {finding_id} not found", 1)
        result = store.load_result(row.review)
        render_finding(console, result, store.domain_finding(row), verbose=True)


def _set_status(finding_id: str, status: FindingStatus, note: str | None) -> None:
    settings = _settings()
    with _db(settings).transaction() as s:
        store = Store(s)
        row = store.finding_for(store.local_user(), finding_id)
        if row is None:
            raise _fail(f"finding {finding_id} not found", 1)
        store.set_status(row, status, store.local_user(), note)
    console.print(f"{finding_id} → [bold]{status.value}[/]")


@app.command()
def dismiss(finding_id: str, note: Annotated[str | None, typer.Option(help="Why.")] = None) -> None:
    """Mark a finding as dismissed (false positive / won't fix)."""
    _set_status(finding_id, FindingStatus.DISMISSED, note)


@app.command()
def accept(
    finding_id: str, note: Annotated[str | None, typer.Option(help="Comment.")] = None
) -> None:
    """Mark a finding as accepted (real issue, to be fixed)."""
    _set_status(finding_id, FindingStatus.ACCEPTED, note)


# --------------------------------------------------------------------------- fix


@app.command()
def fix(
    finding_id: Annotated[str | None, typer.Argument(help="Finding ID.")] = None,
    finding_opt: Annotated[str | None, typer.Option("--finding", help="Finding ID.")] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Write the validated patch to disk.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask for confirmation.")] = False,
    sandbox: Annotated[
        str | None, typer.Option(help="docker | process (process = reduced isolation)")
    ] = None,
) -> None:
    """Generate a fix for a finding, validate it in a sandbox, optionally apply it."""
    target = finding_id or finding_opt
    if not target:
        raise _fail("pass a finding ID: sentinel fix F-…")
    overrides: dict[str, Any] = {}
    if sandbox:
        overrides["sandbox"] = sandbox
        if sandbox == "process":
            overrides["allow_process_sandbox"] = True
    settings = _settings(**overrides)
    db = _db(settings)
    with db.transaction() as s:
        store = Store(s)
        row = store.finding_for(store.local_user(), target)
        if row is None:
            raise _fail(f"finding {target} not found", 1)
        finding = store.domain_finding(row)
        local_path = row.review.repository.local_path
        fix_row = store.create_fix(row)
        fix_id = fix_row.id
    if not local_path:
        raise _fail("this finding is not from a local repository")
    root = Path(local_path)
    try:
        engine = build_fix_engine(settings, load_repo_config(root), workspace=root)
    except AIConfigurationError as exc:
        raise _fail(str(exc)) from exc
    with console.status(f"Generating and validating a fix for {finding.id} …"):
        try:
            outcome = engine.generate(finding, root)
        except AIError as exc:
            raise _fail(str(exc), EXIT_FAILED) from exc
    from sentinel.services.fixes import FixService

    FixService(db, settings)._save(fix_id, outcome)
    if outcome.patch:
        console.print(
            Panel(
                Syntax(outcome.patch, "diff", theme="ansi_dark"),
                title=f"Proposed patch ({fix_id})",
                subtitle=escape(outcome.summary),
            )
        )
    table = Table(title=f"Fix validation — isolation: {outcome.isolation}", header_style="bold")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail", style="dim")
    icon = {
        "passed": "[green]✓ passed[/]",
        "failed": "[red]✗ failed[/]",
        "skipped": "[yellow]– skipped[/]",
        "error": "[red]! error[/]",
    }
    for c in outcome.checks:
        table.add_row(c.name, icon[c.status], escape(c.detail))
    console.print(table)
    verdict = {
        "validated": "[bold green]Patch validated.[/]",
        "unverified": "[bold yellow]Patch applies cleanly but could not be verified by tests "
        "or a deterministic re-check.[/]",
        "failed": "[bold red]Patch failed validation.[/]",
        "error": f"[bold red]Fix generation failed:[/] {escape(outcome.error or '')}",
    }[outcome.status]
    console.print(verdict)
    wants_apply = apply and outcome.status in ("validated", "unverified")
    if wants_apply and (yes or typer.confirm("Apply this patch to your working tree?")):
        try:
            written = apply_fix(root, outcome)
        except ApplyError as exc:
            raise _fail(str(exc), EXIT_FAILED) from exc
        with db.transaction() as s:
            store = Store(s)
            fr = store.finding_for(store.local_user(), finding.id)
            if fr is not None:
                store.set_status(fr, FindingStatus.FIXED, store.local_user(), f"applied {fix_id}")
        console.print(f"[green]Applied to {', '.join(written)}[/]")
    if outcome.status in ("failed", "error"):
        raise typer.Exit(EXIT_FAILED)


# --------------------------------------------------------------------------- config


@config_app.callback(invoke_without_command=True)
def config_show(ctx: typer.Context) -> None:
    """Show effective settings (secrets masked)."""
    if ctx.invoked_subcommand is not None:
        return
    settings = _settings()
    table = Table(title=f"Settings ({user_config_path()})", header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for key, value in settings.model_dump().items():
        if key in SECRET_KEYS or key.endswith("secret"):
            value = "set" if value else "not set"
        table.add_row(key, escape(str(value)))
    table.add_row("model (effective)", settings.resolved_model)
    console.print(table)


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Persist a setting, e.g. `sentinel config set provider claude`."""
    try:
        path = save_user_setting(key, value)
    except (ConfigError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    shown = "****" if key in SECRET_KEYS else value
    console.print(f"Saved {key} = {shown} to {path}")


@config_app.command("init")
def config_init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write a .sentinel.yml template to the current repository."""
    root = repo_root(Path.cwd())
    target = root / ".sentinel.yml"
    if target.exists() and not force:
        raise _fail(f"{target} exists (use --force)")
    target.write_text(REPO_CONFIG_TEMPLATE, encoding="utf-8")
    console.print(f"Wrote {target}")


# --------------------------------------------------------------------------- servers & admin


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 8000,
    worker: Annotated[
        bool, typer.Option("--worker/--no-worker", help="Run a worker in-process.")
    ] = True,
) -> None:
    """Run the API + web UI (and, by default, a background worker)."""
    import uvicorn

    from sentinel.apps.api.app import create_app
    from sentinel.apps.worker.main import Worker
    from sentinel.services.fixes import FixService

    settings = _settings()
    if host not in ("127.0.0.1", "localhost", "::1") and settings.auth_mode == "local":
        raise _fail(
            "refusing to bind a no-auth server to a public interface; set SENTINEL_AUTH_MODE=token"
        )
    configure_logging(settings.log_format)
    db = _db(settings)
    gh = github_factory(settings) if (settings.github_token or settings.github_app_id) else None
    reviews_svc = ReviewService(db, settings, github_factory=gh, public_url=settings.public_url)
    fixes_svc = FixService(db, settings, github_factory=gh)
    app_ = create_app(
        settings,
        db=db,
        reviews=reviews_svc,
        fixes=fixes_svc,
        worker_factory=(lambda: Worker(db, reviews_svc, fixes_svc)) if worker else None,
    )
    console.print(f"Sentinel on [bold]http://{host}:{port}[/] (auth: {settings.auth_mode})")
    uvicorn.run(app_, host=host, port=port, log_level="warning")


@app.command("worker")
def worker_cmd() -> None:
    """Run a background worker that processes queued reviews, fixes and GitHub publishing."""
    from sentinel.apps.worker.main import Worker
    from sentinel.services.fixes import FixService

    settings = _settings()
    configure_logging(settings.log_format)
    db = _db(settings)
    gh = github_factory(settings) if (settings.github_token or settings.github_app_id) else None
    Worker(
        db,
        ReviewService(db, settings, github_factory=gh, public_url=settings.public_url),
        FixService(db, settings, github_factory=gh),
    ).run_forever()


@users_app.command("create")
def users_create(
    name: str, admin: Annotated[bool, typer.Option("--admin", help="Grant admin.")] = False
) -> None:
    """Create an API user and print its token (shown once)."""
    settings = _settings()
    with _db(settings).transaction() as s:
        user, token = Store(s).create_user(name, is_admin=admin)
    console.print(f"Created {user.id} ({name}). Token (store it now, it is not shown again):")
    console.print(token, highlight=False)


@users_app.command("link-installation")
def users_link(installation_id: int, user_id: str, account: str | None = None) -> None:
    """Give a user ownership of a GitHub App installation's repositories."""
    settings = _settings()
    with _db(settings).transaction() as s:
        from sentinel.infrastructure.database.models import User

        store = Store(s)
        user = s.get(User, user_id)
        if user is None:
            raise _fail(f"user {user_id} not found", 1)
        store.link_installation(installation_id, user, account)
    console.print(f"Installation {installation_id} → {user_id}")


@app.command()
def graph(
    target: Annotated[Path, typer.Argument(help="Repository or directory.")] = Path("."),
    symbol: Annotated[str | None, typer.Option(help="Show callers/callees of this symbol.")] = None,
) -> None:
    """Print code-graph statistics (debugging aid)."""
    from sentinel.analysis.ast.registry import default_registry
    from sentinel.analysis.graph.builder import build_graph
    from sentinel.core.review.workspace import collect_sources

    root = repo_root(target.resolve())
    exts = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
    snap = collect_sources(root, exts, [])
    res = build_graph(default_registry(search_roots=(root,)).analyze(snap.sources))
    g = res.graph
    console.print(
        f"{len(snap.sources)} files · {len(g)} nodes · {len(g.edges)} edges · "
        f"{res.resolved_calls} resolved / {res.unresolved_calls} unresolved calls"
    )
    if symbol:
        for node in g.find_by_name(symbol):
            console.print(f"[bold]{node.name}[/] ({node.file}:{node.line_start})")
            console.print("  callers: " + ", ".join(n.name for n in g.callers(node.id)))
            console.print("  callees: " + ", ".join(n.name for n in g.callees(node.id)))
            path = g.path_from_entrypoint(node.id)
            if path:
                console.print("  entry:   " + " → ".join(n.name for n in path))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
