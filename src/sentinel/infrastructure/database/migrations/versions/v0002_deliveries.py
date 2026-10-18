"""Add atomic webhook delivery and revision reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_deliveries"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add delivery keys while preserving all existing reviews and jobs."""
    op.create_table(
        "github_deliveries",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(40),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove delivery keys; this loses deduplication history and is never automatic."""
    op.drop_table("github_deliveries")
