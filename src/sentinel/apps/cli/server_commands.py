"""Long-running processes and administration: ``serve``, ``worker``, ``users``, ``graph``.

``serve`` runs the HTTP API and web UI (``apps/api``) and, by default, a worker thread;
``worker`` runs only the job worker (``apps/worker``), for deployments with several.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from sentinel.apps.cli.common import (
    EXIT_NOT_FOUND,
    console,
    fail,
    load_cli_settings,
    open_database,
)
from sentinel.bootstrap import build_sandbox, github_factory
from sentinel.core.configuration.config import Settings
from sentinel.core.review.orchestrator import SOURCE_EXTENSIONS
from sentinel.infrastructure.database.models import User
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.infrastructure.observability.logging import configure_logging
from sentinel.services.fixes import FixService
from sentinel.services.reviews import GitHubFactory, ReviewService

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port.")] = DEFAULT_PORT,
    worker: Annotated[
        bool, typer.Option("--worker/--no-worker", help="Run a worker in-process.")
    ] = True,
) -> None:
    """Run the API + web UI (and, by default, a background worker)."""
    import uvicorn  # imported here: only this command needs the web server

    from sentinel.apps.api.app import create_app
    from sentinel.apps.worker.main import Worker

    settings = load_cli_settings()
    if host not in LOOPBACK_HOSTS and settings.auth_mode == "local":
        raise fail(
            "refusing to bind a no-auth server to a public interface; set SENTINEL_AUTH_MODE=token"
        )
    configure_logging(settings.log_format)
    db, reviews, fixes = _services(settings)
    application = create_app(
        settings,
        db=db,
        reviews=reviews,
        fixes=fixes,
        worker_factory=(lambda: Worker(db, reviews, fixes)) if worker else None,
    )
    console.print(f"Sentinel on [bold]http://{host}:{port}[/] (auth: {settings.auth_mode})")
    uvicorn.run(application, host=host, port=port, log_level="warning")


def worker(
    kind: Annotated[
        list[str] | None, typer.Option("--kind", help="Job kind; repeat to select several.")
    ] = None,
    require_sandbox: Annotated[
        bool,
        typer.Option("--require-sandbox", help="Refuse startup without the Docker fix sandbox."),
    ] = False,
) -> None:
    """Run a background worker that processes queued reviews, fixes and GitHub publishing."""
    from sentinel.apps.worker.main import Worker

    settings = load_cli_settings()
    configure_logging(settings.log_format)
    if kind is not None and (not kind or set(kind) - {"review", "publish", "fix"}):
        raise typer.BadParameter("worker kinds must be review, publish or fix", param_hint="--kind")
    if require_sandbox:
        sandbox = build_sandbox(settings)
        if sandbox is None or sandbox.isolation != "docker":
            raise fail("Docker fix sandbox is unavailable; build the image and check daemon access")
    Worker(*_services(settings), kinds=kind).run_forever()


def users_create(
    name: str, admin: Annotated[bool, typer.Option("--admin", help="Grant admin.")] = False
) -> None:
    """Create an API user and print its token (shown once)."""
    with open_database(load_cli_settings()).transaction() as session:
        user, token = Store(session).create_user(name, is_admin=admin)
    console.print(f"Created {user.id} ({name}). Token (store it now, it is not shown again):")
    console.print(token, highlight=False)


def users_link(installation_id: int, user_id: str, account: str | None = None) -> None:
    """Give a user ownership of a GitHub App installation's repositories."""
    with open_database(load_cli_settings()).transaction() as session:
        user = session.get(User, user_id)
        if user is None:
            raise fail(f"user {user_id} not found", EXIT_NOT_FOUND)
        Store(session).link_installation(installation_id, user, account)
    console.print(f"Installation {installation_id} → {user_id}")


def graph(
    target: Annotated[Path, typer.Argument(help="Repository or directory.")] = Path("."),
    symbol: Annotated[str | None, typer.Option(help="Show callers/callees of this symbol.")] = None,
) -> None:
    """Print code-graph statistics (debugging aid)."""
    from sentinel.analysis.ast.registry import default_registry
    from sentinel.analysis.diff.git import repo_root
    from sentinel.analysis.graph.builder import build_graph
    from sentinel.core.review.workspace import collect_sources

    root = repo_root(target.resolve())
    snapshot = collect_sources(root, set(SOURCE_EXTENSIONS), [])
    built = build_graph(default_registry(search_roots=(root,)).analyze(snapshot.sources))
    code_graph = built.graph
    console.print(
        f"{len(snapshot.sources)} files · {len(code_graph)} nodes · "
        f"{len(code_graph.edges)} edges · "
        f"{built.resolved_calls} resolved / {built.unresolved_calls} unresolved calls"
    )
    for node in code_graph.find_by_name(symbol) if symbol else []:
        console.print(f"[bold]{node.name}[/] ({node.file}:{node.line_start})")
        console.print("  callers: " + ", ".join(n.name for n in code_graph.callers(node.id)))
        console.print("  callees: " + ", ".join(n.name for n in code_graph.callees(node.id)))
        path = code_graph.path_from_entrypoint(node.id)
        if path:
            console.print("  entry:   " + " → ".join(n.name for n in path))


def _services(settings: Settings) -> tuple[Database, ReviewService, FixService]:
    """Database plus the review and fix services, with GitHub wired in when configured."""
    db = open_database(settings)
    gh: GitHubFactory | None = (
        github_factory(settings) if (settings.github_token or settings.github_app_id) else None
    )
    reviews = ReviewService(db, settings, github_factory=gh, public_url=settings.public_url)
    return db, reviews, FixService(db, settings, github_factory=gh)
