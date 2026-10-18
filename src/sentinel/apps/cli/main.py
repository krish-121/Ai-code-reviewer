"""The ``sentinel`` command-line interface: every command, and where it is implemented.

Entry point: ``sentinel = sentinel.apps.cli.main:main`` (pyproject.toml). Commands are
plain functions in the ``*_commands.py`` modules next to this one; this file only
registers them, so it doubles as a table of contents for the CLI.
"""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from sentinel import __version__
from sentinel.apps.cli import (
    config_commands,
    database_commands,
    finding_commands,
    fix_command,
    review_commands,
    server_commands,
)
from sentinel.apps.cli.common import console
from sentinel.infrastructure.observability.logging import configure_logging

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
database_app = typer.Typer(help="Inspect or upgrade the database schema.", no_args_is_help=True)
app.add_typer(database_app, name="db")
database_app.command("status")(database_commands.database_status)
database_app.command("upgrade")(database_commands.database_upgrade)

# Reviewing
app.command()(review_commands.review)
app.command()(fix_command.fix)
# History and triage
app.command()(finding_commands.reviews)
app.command()(finding_commands.findings)
app.command()(finding_commands.show)
app.command()(finding_commands.accept)
app.command()(finding_commands.dismiss)
# Settings
config_app.callback(invoke_without_command=True)(config_commands.config_show)
config_app.command("set")(config_commands.config_set)
config_app.command("init")(config_commands.config_init)
# Servers and administration
app.command()(server_commands.serve)
app.command("worker")(server_commands.worker)
users_app.command("create")(server_commands.users_create)
users_app.command("link-installation")(server_commands.users_link)
app.command()(server_commands.graph)


def _show_version(value: bool) -> None:
    if value:
        console.print(f"sentinel {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show version."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    """Options that apply to every command."""
    configure_logging("text", logging.DEBUG if verbose else logging.WARNING)


def main() -> None:
    """Run the CLI (console-script entry point)."""
    app()


if __name__ == "__main__":
    main()
