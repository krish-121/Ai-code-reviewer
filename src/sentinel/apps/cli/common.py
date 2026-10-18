"""Helpers shared by every CLI command: consoles, exit codes, settings and database.

Error handling is the same in every command: an expected problem (a ``SentinelError``
such as a bad setting or a missing git repository) is printed in red with ``fail`` and
the command exits with one of the codes below; anything else is a bug and shows a
traceback.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

from sentinel.bootstrap import FROM_SETTINGS
from sentinel.core.configuration.config import ConfigError, Settings, load_settings
from sentinel.core.domain.ports import AIProvider
from sentinel.infrastructure.database.schema import SchemaError
from sentinel.infrastructure.database.session import Database
from sentinel.services.reviews import AIFactory

console = Console()
err = Console(stderr=True)

EXIT_FINDINGS = 1  # `--fail-on` threshold reached (useful in CI)
EXIT_NOT_FOUND = 1
EXIT_CONFIG = 2  # bad settings, not a git repository, provider not configured ...
EXIT_FAILED = 3  # the review or fix itself failed


def fail(message: str, code: int = EXIT_CONFIG) -> typer.Exit:
    """Print an error and return the ``typer.Exit`` for the caller to raise."""
    err.print(f"[bold red]ERROR:[/] {escape(message)}")
    return typer.Exit(code)


def load_cli_settings(**overrides: Any) -> Settings:
    """Settings from file and environment, plus command-line overrides."""
    try:
        return load_settings(overrides=overrides)
    except ConfigError as exc:
        raise fail(str(exc)) from exc


def open_database(settings: Settings) -> Database:
    """Connect to the configured database and create tables if needed."""
    db = Database(settings.database_url)
    try:
        db.create_all()
    except SchemaError as exc:
        db.engine.dispose()
        raise fail(str(exc)) from exc
    return db


def ai_factory_for(no_ai: bool) -> AIFactory:
    """Provider factory for ``--no-ai`` (no provider) or the configured provider."""

    def factory() -> AIProvider | str | None:
        return None if no_ai else FROM_SETTINGS

    return factory
