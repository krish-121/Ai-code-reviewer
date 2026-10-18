"""``sentinel config``: show settings, save one, or write a ``.sentinel.yml`` template.

User settings (provider, model, API keys ...) live in ``~/.config/sentinel/config.toml``
(see ``core/configuration/config.py``); per-repository review rules live in
``.sentinel.yml`` at the repository root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from sentinel.analysis.diff.git import repo_root
from sentinel.apps.cli.common import console, fail, load_cli_settings
from sentinel.core.configuration.config import (
    SECRET_KEYS,
    ConfigError,
    save_user_setting,
    user_config_path,
)

REPO_CONFIG_FILE = ".sentinel.yml"
MASK = "****"
REPO_CONFIG_TEMPLATE = """\
# Sentinel review configuration
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


def config_show(ctx: typer.Context) -> None:
    """Show effective settings (secrets masked)."""
    if ctx.invoked_subcommand is not None:
        return
    settings = load_cli_settings()
    table = Table(title=f"Settings ({user_config_path()})", header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for key, value in settings.model_dump().items():
        is_secret = key in SECRET_KEYS or key.endswith("secret")
        shown = ("set" if value else "not set") if is_secret else value
        table.add_row(key, escape(str(shown)))
    table.add_row("model (effective)", settings.resolved_model)
    console.print(table)


def config_set(key: str, value: Annotated[str | None, typer.Argument()] = None) -> None:
    """Persist a setting; omit a secret's value to enter it at a hidden prompt."""
    if value is None:
        if key not in SECRET_KEYS:
            raise fail("Provide a value for non-secret settings.")
        value = typer.prompt(f"Enter {key}", hide_input=True)
    try:
        path = save_user_setting(key, value)
    except (ConfigError, ValueError) as exc:
        raise fail(str(exc)) from exc
    shown = MASK if key in SECRET_KEYS else value
    console.print(f"Saved {key} = {shown} to {path}")


def config_init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write a .sentinel.yml template to the current repository."""
    target = repo_root(Path.cwd()) / REPO_CONFIG_FILE
    if target.exists() and not force:
        raise fail(f"{target} exists (use --force)")
    target.write_text(REPO_CONFIG_TEMPLATE, encoding="utf-8")
    console.print(f"Wrote {target}")
