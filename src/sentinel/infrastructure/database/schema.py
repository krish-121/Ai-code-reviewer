"""Versioned schema lifecycle: explicit upgrades, strict legacy adoption, safe startup.

PostgreSQL advisory locks and SQLite immediate transactions serialize cooperating
initializers. Migration DDL and the Alembic revision are committed together. Startup
initializes empty databases; populated databases must already be at the current revision.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from sentinel.core.domain.errors import SentinelError
from sentinel.infrastructure.database.migrations.legacy_schema import metadata

MIGRATION_LOCK = 1397050964
FIRST_REVISION = "0001_initial"
DELIVERY_REVISION = "0002_deliveries"
_local_lock = RLock()  # Alembic's environment proxy is process-global.


class SchemaError(SentinelError):
    """The database is incompatible or needs an explicit upgrade."""


def migration_config(connection: Connection | None = None) -> Config:
    """Locate revision files inside the installed package, independent of cwd."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    """The single schema revision supported by this application build."""
    revision = ScriptDirectory.from_config(migration_config()).get_current_head()
    if revision is None:
        raise SchemaError("migration history has no head")
    return revision


def status(engine: Engine) -> dict[str, Any]:
    """Read schema status without changing the database."""
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
    head = head_revision()
    return {
        "revision": current,
        "head": head,
        "current": current == head,
        "unversioned": current is None and bool(tables),
    }


@contextmanager
def locked(engine: Engine) -> Iterator[Connection]:
    """Serialize migration/startup operations and make revision changes transactional."""
    with _local_lock, engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif engine.dialect.name == "postgresql":
            connection.begin()
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        else:
            raise SchemaError("schema migration supports SQLite and PostgreSQL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def initialize(engine: Engine) -> None:
    """Initialize empty databases, refusing implicit upgrades or legacy stamping."""
    with locked(engine) as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        if current is None and not tables:
            command.upgrade(migration_config(connection), "head")
        elif current != head_revision():
            raise SchemaError(
                "database needs migration; back it up, then run sentinel db upgrade "
                "(--adopt-legacy for an unversioned database)"
            )
        elif set(metadata(deliveries=True).tables) - tables:
            raise SchemaError("versioned database is missing tables; restore or repair the schema")


def upgrade(engine: Engine, *, adopt_legacy: bool = False) -> str:
    """Upgrade under a lock; legacy adoption validates the frozen historical schema."""
    try:
        with locked(engine) as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            config = migration_config(connection)
            if current is None and tables:
                if not adopt_legacy:
                    raise SchemaError("unversioned database: back up and use --adopt-legacy")
                _adopt(connection, config, tables)
            command.upgrade(config, "head")
    except CommandError as exc:
        raise SchemaError(f"cannot upgrade database revision: {exc}") from exc
    return head_revision()


def _adopt(connection: Connection, config: Config, tables: set[str]) -> None:
    deliveries = "github_deliveries" in tables
    expected = metadata(deliveries=deliveries)
    differences = compare_metadata(
        MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        ),
        expected,
    )
    inspector = inspect(connection)
    for name, table in expected.tables.items():
        if name not in tables:
            continue
        actual_pk = inspector.get_pk_constraint(name).get("constrained_columns", [])
        if actual_pk != [c.name for c in table.primary_key.columns]:
            differences.append(("primary_key", name))
        if inspector.get_check_constraints(name):
            differences.append(("unsupported_check_constraint", name))
    if differences:
        raise SchemaError(
            "legacy schema differs from the supported historical schema; "
            "no revision was stamped; restore or migrate it manually"
        )
    command.stamp(config, DELIVERY_REVISION if deliveries else FIRST_REVISION)
