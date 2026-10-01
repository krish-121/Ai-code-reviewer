"""Review history and finding triage: ``reviews``, ``findings``, ``show``, ``accept``, ``dismiss``.

These commands only read and update the local database (``Store``); they never run a
review.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from sentinel.apps.cli.common import (
    EXIT_NOT_FOUND,
    console,
    fail,
    load_cli_settings,
    open_database,
)
from sentinel.apps.cli.render import findings_table, render_finding
from sentinel.core.domain.models import FindingStatus, ReviewResult
from sentinel.infrastructure.database.models import Review
from sentinel.infrastructure.database.store import Store

REVIEW_COLUMNS = ("ID", "When", "Title", "Status", "Risk", "High", "Med", "Low")
DATE_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_REVIEW_LIMIT = 15


def reviews(
    limit: Annotated[int, typer.Option(help="How many to show.")] = DEFAULT_REVIEW_LIMIT,
) -> None:
    """List past reviews."""
    with open_database(load_cli_settings()).transaction() as session:
        store = Store(session)
        table = Table(header_style="bold")
        for column in REVIEW_COLUMNS:
            table.add_column(column)
        for row in store.list_reviews(store.local_user(), limit=limit):
            counts = ((row.summary or {}).get("stats") or {}).get("by_severity", {})
            table.add_row(
                row.id,
                row.created_at.strftime(DATE_FORMAT),
                escape(row.title or ""),
                row.status,
                row.risk or "-",
                *(str(counts.get(s, 0)) for s in ("high", "medium", "low")),
            )
        console.print(table)


def findings(
    review_id: Annotated[
        str | None, typer.Option("--review", help="Review ID (default: latest).")
    ] = None,
    show_all: Annotated[bool, typer.Option("--all", help="Include suppressed findings.")] = False,
) -> None:
    """List findings of a review."""
    with open_database(load_cli_settings()).transaction() as session:
        row, result = _load_review(Store(session), review_id)
        console.print(findings_table(result.findings, f"{row.id} — {row.title}"))
        if show_all and result.suppressed:
            console.print(findings_table(result.suppressed, "Suppressed"))


def show(finding_id: Annotated[str, typer.Argument(help="Finding ID, e.g. F-3fa9c2d1e0")]) -> None:
    """Show one finding with its evidence and verification checks."""
    with open_database(load_cli_settings()).transaction() as session:
        store = Store(session)
        row = store.finding_for(store.local_user(), finding_id)
        if row is None:
            raise fail(f"finding {finding_id} not found", EXIT_NOT_FOUND)
        result = store.load_result(row.review)
        render_finding(console, result, store.domain_finding(row), verbose=True)


def dismiss(finding_id: str, note: Annotated[str | None, typer.Option(help="Why.")] = None) -> None:
    """Mark a finding as dismissed (false positive / won't fix)."""
    _set_status(finding_id, FindingStatus.DISMISSED, note)


def accept(
    finding_id: str, note: Annotated[str | None, typer.Option(help="Comment.")] = None
) -> None:
    """Mark a finding as accepted (real issue, to be fixed)."""
    _set_status(finding_id, FindingStatus.ACCEPTED, note)


def _load_review(store: Store, review_id: str | None) -> tuple[Review, ReviewResult]:
    """The given review, or the latest one."""
    user = store.local_user()
    row = store.review_for(user, review_id) if review_id else store.latest_review(user)
    if row is None:
        raise fail("no review found; run `sentinel review` first", EXIT_NOT_FOUND)
    return row, store.load_result(row)


def _set_status(finding_id: str, status: FindingStatus, note: str | None) -> None:
    with open_database(load_cli_settings()).transaction() as session:
        store = Store(session)
        row = store.finding_for(store.local_user(), finding_id)
        if row is None:
            raise fail(f"finding {finding_id} not found", EXIT_NOT_FOUND)
        store.set_status(row, status, store.local_user(), note)
    console.print(f"{finding_id} → [bold]{status.value}[/]")
