"""Initial review, account, fix and job tables (historical schema snapshot)."""

from alembic import op

from sentinel.infrastructure.database.migrations.legacy_schema import metadata

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Build the frozen initial schema, independent of future ORM changes."""
    metadata().create_all(op.get_bind())


def downgrade() -> None:
    """Remove initial tables; destructive, for explicit offline recovery/testing only."""
    metadata().drop_all(op.get_bind())
