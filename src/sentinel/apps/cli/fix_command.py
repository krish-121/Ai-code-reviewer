"""``sentinel fix``: generate a fix for a finding, validate it in a sandbox, maybe apply it.

Flow: look up the finding -> ``build_fix_engine`` -> ``FixEngine.generate`` (AI patch ->
scratch copy -> syntax and re-analysis checks -> tests in the sandbox) -> print the patch
and the checks -> with ``--apply``, write it to the working tree via ``apply_fix``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from sentinel.apps.cli.common import (
    EXIT_FAILED,
    EXIT_NOT_FOUND,
    console,
    fail,
    load_cli_settings,
    open_database,
)
from sentinel.bootstrap import build_fix_engine
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import Finding
from sentinel.core.domain.ports import AIConfigurationError
from sentinel.core.fixes.engine import FixOutcome
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.fixes import FixService
from sentinel.services.resources import close_provider

UNSUCCESSFUL = ("failed", "error")
PROCESS_SANDBOX = "process"
CHECK_ICONS = {
    "passed": "[green]✓ passed[/]",
    "failed": "[red]✗ failed[/]",
    "skipped": "[yellow]– skipped[/]",
    "error": "[red]! error[/]",
}
VERDICTS = {
    "validated": "[bold green]Patch validated.[/]",
    "unverified": "[bold yellow]Patch applies cleanly but could not be verified by all required "
    "analysis and sandbox test checks.[/]",
    "failed": "[bold red]Patch failed validation.[/]",
    "error": "[bold red]Fix generation failed:[/] {error}",
}


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
        raise fail("pass a finding ID: sentinel fix F-…")
    settings = load_cli_settings(**_sandbox_overrides(sandbox))
    db = open_database(settings)
    finding, root, fix_id = _start_fix(db, target)
    outcome = _generate(settings, finding, root)
    FixService(db, settings).save_outcome(fix_id, outcome)
    _print_outcome(fix_id, outcome)
    if apply and not outcome.ok:
        raise fail(
            "Only validated patches can be applied; complete the missing checks first", EXIT_FAILED
        )
    wants_apply = apply and outcome.ok
    if wants_apply and (yes or typer.confirm("Apply this patch to your working tree?")):
        _apply(db, settings, fix_id)
    if outcome.status in UNSUCCESSFUL:
        raise typer.Exit(EXIT_FAILED)


def _sandbox_overrides(sandbox: str | None) -> dict[str, Any]:
    """``--sandbox process`` must also opt in to the weaker isolation explicitly."""
    if not sandbox:
        return {}
    overrides: dict[str, Any] = {"sandbox": sandbox}
    if sandbox == PROCESS_SANDBOX:
        overrides["allow_process_sandbox"] = True
    return overrides


def _start_fix(db: Database, finding_id: str) -> tuple[Finding, Path, str]:
    """Look up the finding and create its ``FixAttempt`` row; returns (finding, repo, fix id)."""
    with db.transaction() as session:
        store = Store(session)
        row = store.finding_for(store.local_user(), finding_id)
        if row is None:
            raise fail(f"finding {finding_id} not found", EXIT_NOT_FOUND)
        finding = store.domain_finding(row)
        local_path = row.review.request.get("path")
        fix_id = store.create_fix(row).id
    if not local_path:
        raise fail("this finding is not from a local repository")
    return finding, Path(local_path), fix_id


def _generate(settings: Settings, finding: Finding, root: Path) -> FixOutcome:
    try:
        engine = build_fix_engine(settings, load_repo_config(root), workspace=root)
    except AIConfigurationError as exc:
        raise fail(str(exc)) from exc
    with console.status(f"Generating and validating a fix for {finding.id} …"):
        try:
            return engine.generate(finding, root)
        except SentinelError as exc:
            raise fail(str(exc), EXIT_FAILED) from exc
        finally:
            close_provider(engine)


def _print_outcome(fix_id: str, outcome: FixOutcome) -> None:
    """The patch, a table of validation checks, and a one-line verdict."""
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
    for check in outcome.checks:
        table.add_row(check.name, CHECK_ICONS[check.status], escape(check.detail))
    console.print(table)
    console.print(VERDICTS[outcome.status].format(error=escape(outcome.error or "")))


def _apply(db: Database, settings: Settings, fix_id: str) -> None:
    """Write the patch and mark the finding as fixed."""
    try:
        written = FixService(db, settings).apply(fix_id)
    except SentinelError as exc:
        raise fail(str(exc), EXIT_FAILED) from exc
    console.print(f"[green]Applied to {', '.join(written)}[/]")
