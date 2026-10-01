"""Request-scoped dependencies shared by every route module.

``create_app`` (in ``app.py``) stores one ``ApiContext`` on ``app.state``. The functions
here hand each request what it needs from it: a database session, the current user, the
application services. Routes declare their needs with the ``ContextDep`` / ``SessionDep`` /
``UserDep`` aliases, so no route builds its own infrastructure.

Tenancy lives here too: the ``*_or_404`` helpers look rows up *through the current user*,
so a review another user owns is indistinguishable from one that does not exist.
"""

# No `from __future__ import annotations`: FastAPI evaluates these Annotated aliases.

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from sentinel.core.configuration.config import Settings
from sentinel.infrastructure.database.models import Finding as FindingRow
from sentinel.infrastructure.database.models import FixAttempt, Review, User
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService

LOCAL_AUTH_MODE = "local"
BEARER_PREFIX = "Bearer "


@dataclass(frozen=True)
class ApiContext:
    """Long-lived objects the routes use, created once by ``create_app``."""

    settings: Settings
    database: Database
    reviews: ReviewService
    fixes: FixService
    static_dir: Path


def get_context(request: Request) -> ApiContext:
    """Return the ``ApiContext`` that ``create_app`` stored on the application."""
    context: ApiContext = request.app.state.context
    return context


ContextDep = Annotated[ApiContext, Depends(get_context)]


def get_session(context: ContextDep) -> Iterator[Session]:
    """Open one database transaction per request; it commits when the route returns."""
    with context.database.transaction() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_user(
    context: ContextDep,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller: the single local user, or the owner of a bearer token."""
    store = Store(session)
    if context.settings.auth_mode == LOCAL_AUTH_MODE:
        return store.local_user()
    token = (authorization or "").removeprefix(BEARER_PREFIX).strip()
    user = store.user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="missing or invalid API token")
    return user


UserDep = Annotated[User, Depends(get_user)]


def require_client_header(x_sentinel_client: Annotated[str | None, Header()] = None) -> None:
    """Reject state-changing requests that lack the ``X-Sentinel-Client`` header.

    A cross-site form cannot add a custom header without a CORS preflight, which this
    server never approves, so the header is a cheap and reliable CSRF guard.
    """
    if not x_sentinel_client:
        raise HTTPException(status_code=403, detail="missing X-Sentinel-Client header")


# Add to a route as ``dependencies=MUTATING`` when it changes state.
MUTATING = [Depends(require_client_header)]


def review_or_404(store: Store, user: User, review_id: str) -> Review:
    """The user's review with this id, or HTTP 404."""
    review = store.review_for(user, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not found")
    return review


def finding_or_404(store: Store, user: User, finding_id: str) -> FindingRow:
    """The user's finding with this id, or HTTP 404."""
    row = store.finding_for(user, finding_id)
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return row


def fix_or_404(store: Store, user: User, fix_id: str) -> FixAttempt:
    """The user's fix attempt with this id, or HTTP 404."""
    fix = store.fix_for(user, fix_id)
    if fix is None:
        raise HTTPException(status_code=404, detail="fix not found")
    return fix
