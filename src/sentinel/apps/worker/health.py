"""Compose worker readiness: current database schema and optional Docker availability.

The container healthcheck calls this installed module. It does not claim a job or need
an AI-provider request; actual sandbox execution is covered by deployment acceptance.
"""

from __future__ import annotations

import sys

from sentinel.bootstrap import build_sandbox
from sentinel.core.configuration.config import Settings, load_settings
from sentinel.infrastructure.database.schema import status
from sentinel.infrastructure.database.session import Database


def ready(settings: Settings, *, require_sandbox: bool = False) -> bool:
    """Check database compatibility and the Docker CLI/image required by a fix worker."""
    database = Database(settings.database_url)
    try:
        current = bool(status(database.engine)["current"])
    finally:
        database.engine.dispose()
    if not current:
        return False
    if require_sandbox:
        sandbox = build_sandbox(settings)
        return sandbox is not None and sandbox.isolation == "docker"
    return True


if __name__ == "__main__":
    raise SystemExit(0 if ready(load_settings(), require_sandbox="--sandbox" in sys.argv) else 1)
