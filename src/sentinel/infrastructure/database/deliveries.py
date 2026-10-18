"""Durable unique keys for webhook deliveries and equivalent PR revision requests."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from sentinel.infrastructure.database.models import Base
from sentinel.integrations.github.webhooks import PullRequestEvent


class Delivery(Base):
    """Unique reservations committed atomically with their review and queue job."""

    __tablename__ = "github_deliveries"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))


def delivery_keys(event: PullRequestEvent, delivery_id: str | None) -> list[str]:
    """Coalesce identical revisions even when GitHub assigns another delivery ID."""
    revision = json.dumps(
        [event.repo, event.number, event.installation_id, event.head_sha, event.base_sha]
    )
    keys = ["revision:" + hashlib.sha256(revision.encode()).hexdigest()]
    if delivery_id:
        keys.append("delivery:" + hashlib.sha256(delivery_id.encode()).hexdigest())
    return keys
