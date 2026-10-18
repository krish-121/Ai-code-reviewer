"""Data-preserving schema upgrades and safe startup on SQLite and PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, select, text

from sentinel.infrastructure.database.migrations.legacy_schema import metadata
from sentinel.infrastructure.database.models import User
from sentinel.infrastructure.database.schema import (
    SchemaError,
    head_revision,
    initialize,
    migration_config,
    status,
    upgrade,
)
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from tests.helpers import DATABASE_BACKENDS, fresh_database_url


@pytest.fixture(params=DATABASE_BACKENDS)
def database(tmp_path, request):
    db = Database(fresh_database_url(request.param, tmp_path))
    yield db
    db.engine.dispose()


def legacy(db, deliveries=False):
    metadata(deliveries=deliveries).create_all(db.engine)
    with db.transaction() as session:
        Store(session).local_user()


def test_new_database_runs_all_revisions_and_repeated_startup_is_safe(database):
    assert not status(database.engine)["current"]
    assert "alembic_version" not in inspect(database.engine).get_table_names()
    initialize(database.engine)
    initialize(database.engine)
    assert status(database.engine)["revision"] == head_revision()
    assert "github_deliveries" in inspect(database.engine).get_table_names()


@pytest.mark.parametrize("deliveries", [False, True])
def test_legacy_upgrade_preserves_existing_data_and_requires_explicit_adoption(
    database, deliveries
):
    legacy(database, deliveries)
    from sentinel.infrastructure.database.deliveries import Delivery
    from sentinel.infrastructure.queue import jobs
    from tests.unit.test_store_and_queue import _result

    with database.transaction() as session:
        store = Store(session)
        repository = store.repository(store.local_user(), "legacy-project")
        review = store.create_review(repository, request={"path": "/legacy"}, source="staged")
        store.save_result(review, _result())
        fix = store.create_fix(review.findings[0])
        fix.original_hashes = {"new_test.py": None}
        jobs.enqueue(session, jobs.REVIEW_JOB, {"review_id": review.id})
        if deliveries:
            session.add(Delivery(key="legacy-delivery", review_id=review.id))
    frozen = metadata(deliveries=deliveries)

    def rows():
        with database.engine.connect() as connection:
            return {
                table.name: list(
                    connection.execute(table.select().order_by(*table.primary_key.columns))
                )
                for table in frozen.sorted_tables
            }

    original = rows()
    with pytest.raises(SchemaError, match="needs migration"):
        initialize(database.engine)
    with pytest.raises(SchemaError, match="adopt-legacy"):
        upgrade(database.engine)
    assert "alembic_version" not in inspect(database.engine).get_table_names()
    assert upgrade(database.engine, adopt_legacy=True) == head_revision()
    assert upgrade(database.engine) == head_revision()
    assert rows() == original
    with database.session() as session:
        assert session.scalar(select(User.name)) == "local"


def test_incompatible_legacy_schema_is_never_stamped_or_modified(database):
    legacy(database)
    with database.engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN unrelated INTEGER"))
    before = set(inspect(database.engine).get_table_names())
    with pytest.raises(SchemaError, match="no revision was stamped"):
        upgrade(database.engine, adopt_legacy=True)
    assert set(inspect(database.engine).get_table_names()) == before
    with database.session() as session:
        assert session.scalar(select(User.name)) == "local"


def test_custom_legacy_check_constraint_requires_manual_conversion(database):
    from sqlalchemy import CheckConstraint

    frozen = metadata()
    frozen.tables["users"].append_constraint(
        CheckConstraint("length(name) > 0", name="custom_name")
    )
    frozen.create_all(database.engine)
    with pytest.raises(SchemaError, match="no revision was stamped"):
        upgrade(database.engine, adopt_legacy=True)
    assert "alembic_version" not in inspect(database.engine).get_table_names()


def test_explicit_upgrade_from_recorded_old_revision_preserves_rows(database):
    from alembic import command

    from sentinel.infrastructure.database.schema import locked

    with locked(database.engine) as connection:
        command.upgrade(migration_config(connection), "0001_initial")
    with database.transaction() as session:
        Store(session).local_user()
    with pytest.raises(SchemaError):
        initialize(database.engine)
    upgrade(database.engine)
    initialize(database.engine)
    with database.session() as session:
        assert session.scalar(select(User.name)) == "local"
    with locked(database.engine) as connection:
        command.downgrade(migration_config(connection), "0001_initial")
    assert status(database.engine)["revision"] == "0001_initial"
    upgrade(database.engine)
    with database.session() as session:
        assert session.scalar(select(User.name)) == "local"


def test_unknown_future_revision_is_refused(database):
    initialize(database.engine)
    with database.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'future_release'"))
    with pytest.raises(SchemaError):
        initialize(database.engine)
    with pytest.raises(SchemaError, match="cannot upgrade"):
        upgrade(database.engine)
    assert status(database.engine)["revision"] == "future_release"


def test_failed_upgrade_rolls_back_ddl_and_revision(database, monkeypatch):
    legacy(database)

    def fail(config, revision):
        config.attributes["connection"].execute(text("CREATE TABLE never_commit (id INTEGER)"))
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr("sentinel.infrastructure.database.schema.command.upgrade", fail)
    with pytest.raises(RuntimeError, match="injected"):
        upgrade(database.engine, adopt_legacy=True)
    assert "never_commit" not in inspect(database.engine).get_table_names()
    assert "alembic_version" not in inspect(database.engine).get_table_names()
    with database.session() as session:
        assert session.scalar(select(User.name)) == "local"


def test_concurrent_fresh_initializers_share_one_revision(database):
    def initialize_again(_):
        other = Database(database.url)
        try:
            initialize(other.engine)
        finally:
            other.engine.dispose()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialize_again, range(4)))
    assert status(database.engine)["current"]


def test_revision_package_matches_runtime_schema(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from sentinel.infrastructure.database.deliveries import Delivery

    initialize(database.engine)
    with database.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Delivery.metadata) == []


def test_cli_schema_status_and_explicit_legacy_upgrade(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from sentinel.apps.cli.main import app

    db = Database(f"sqlite:///{tmp_path}/cli.db")
    legacy(db)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", db.url)
    runner = CliRunner()
    result = runner.invoke(app, ["db", "status"])
    assert result.exit_code == 0 and json.loads(result.stdout)["unversioned"]
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 2
    assert runner.invoke(app, ["db", "upgrade", "--adopt-legacy"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["db", "status"]).stdout)["current"]
    db.engine.dispose()
