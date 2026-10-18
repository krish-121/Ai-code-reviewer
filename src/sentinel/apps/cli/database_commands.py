"""Explicit database schema inspection and upgrade commands."""

import json
from typing import Annotated

import typer

from sentinel.apps.cli.common import console, fail, load_cli_settings
from sentinel.infrastructure.database.schema import SchemaError, status, upgrade
from sentinel.infrastructure.database.session import Database


def database_status() -> None:
    """Show the current revision and whether this application can use it."""
    database = Database(load_cli_settings().database_url)
    try:
        typer.echo(json.dumps(status(database.engine)))
    finally:
        database.engine.dispose()


def database_upgrade(
    adopt_legacy: Annotated[
        bool,
        typer.Option("--adopt-legacy", help="Validate and adopt an unversioned Sentinel database."),
    ] = False,
) -> None:
    """Upgrade the schema. Back up existing data and stop API/workers first."""
    database = Database(load_cli_settings().database_url)
    try:
        revision = upgrade(database.engine, adopt_legacy=adopt_legacy)
    except SchemaError as exc:
        raise fail(str(exc)) from exc
    finally:
        database.engine.dispose()
    console.print(f"Database schema is current: {revision}")
