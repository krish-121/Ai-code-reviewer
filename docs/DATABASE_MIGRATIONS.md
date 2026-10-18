# Database upgrades

Sentinel stores the schema revision in `alembic_version`. SQLite and PostgreSQL use the
same packaged Alembic history. The first revision freezes the original account, review,
finding, graph, fix and queue tables; the second adds webhook delivery reservations.
Revision files do not import the latest ORM schema to recreate historical tables.

An empty database is initialized through those revisions on first start. A populated
database must already be current: API/worker/CLI startup refuses implicit upgrades.
No existing user database was upgraded during the engineering checks.

## Upgrade an existing installation

1. Stop the API and workers. Back up the database and verify that you can restore it.
2. Install the new application and inspect the revision with `sentinel db status`.
3. Run `sentinel db upgrade`. For databases made by older releases before schema
   versioning, use `sentinel db upgrade --adopt-legacy` instead.
4. Check `sentinel db status` again, then restart the API and workers.

Use the same `SENTINEL_DATABASE_URL` as the application. Do not copy a database password
into a shell argument or commit it to a configuration file. In Compose, run the upgrade
as a one-off container with the application service's environment, before starting it:

```sh
docker compose stop api worker validation-worker
docker compose run --rm api sentinel db status
docker compose run --rm api sentinel db upgrade --adopt-legacy
docker compose up -d api worker validation-worker
```

Legacy adoption checks the actual schema against the two supported frozen legacy shapes
(with or without `github_deliveries`). It refuses missing/extra columns, tables, changed
types, constraints or indexes instead of stamping a guessed revision. Reviews, findings,
JSON payloads, jobs, fixes and existing delivery keys are preserved. An unknown newer
revision is refused. A database with another historical/custom schema needs an explicit
conversion; restore from backup or write and test that conversion first.

Cooperating initializers serialize using PostgreSQL advisory transaction locks or SQLite
immediate transactions. DDL and the revision stamp share a transaction. This protects
concurrent startup and rollback of failed upgrades; it does not make a live schema change
safe while old application processes are still using it. Keep those processes stopped.

There is no destructive downgrade CLI. The initial revision's downgrade drops tables;
the delivery revision's downgrade loses delivery history. Those routines are tested only
on disposable databases. For production recovery prefer restoring the verified backup
and the matching application version.

## Add a future migration

Install the project editable with its development dependencies. Create a new revision in
`src/sentinel/infrastructure/database/migrations/versions`, using `script.py.mako` as the
template, with a unique `revision` and the current head as `down_revision`. Write explicit
Alembic operations; never edit an applied revision or the frozen legacy snapshot.

Test fresh initialization, upgrade with representative existing records, failed-upgrade
rollback, repeated upgrades and schema/model parity on both SQLite and PostgreSQL.
SQLite changes that require table reconstruction need carefully reviewed batch operations
and foreign-key handling. Consult the [Alembic batch migration documentation](https://alembic.sqlalchemy.org/en/latest/batch.html).

Regression coverage: `tests/integration/test_migrations.py`. The test PostgreSQL URL must
point at a disposable database: test setup drops its schema.
