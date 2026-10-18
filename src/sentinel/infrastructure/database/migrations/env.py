"""Alembic entry point; application commands share their locked transaction."""

from alembic import context

from sentinel.infrastructure.database.deliveries import Delivery


def run_migrations() -> None:
    """Apply migrations using the caller's transaction and connection."""
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "Use sentinel db upgrade; migration commands require a locked connection"
        )
    context.configure(
        connection=connection, target_metadata=Delivery.metadata, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
