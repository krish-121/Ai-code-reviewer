"""HTTP API (FastAPI): builds the application object.

Delivery only: routes (in ``routes/``) translate HTTP into calls on the application
services and back. ``create_app`` wires the services once and stores them in an
``ApiContext`` that every route receives through ``dependencies.py``.

Used by ``sentinel serve`` (``apps/cli``) and by the API tests.

Browser safety for the local, no-login mode: the server binds to localhost, rejects
foreign ``Host`` headers (DNS rebinding), and requires an ``X-Sentinel-Client`` header on
state-changing requests, which cross-site forms cannot send without a CORS preflight.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sentinel import __version__
from sentinel.apps.api.dependencies import LOCAL_AUTH_MODE, ApiContext
from sentinel.apps.api.routes import API_ROUTERS, SPA_ROUTER
from sentinel.core.configuration.config import Settings
from sentinel.infrastructure.database.session import Database
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
WORKER_SHUTDOWN_SECONDS = 5


def create_app(
    settings: Settings,
    *,
    db: Database | None = None,
    reviews: ReviewService | None = None,
    fixes: FixService | None = None,
    worker_factory: Callable[[], Any] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Server configuration (database URL, auth mode, provider ...).
        db: Database to use; created from ``settings`` when omitted.
        reviews: Review service; tests pass one with fake providers.
        fixes: Fix service; tests pass one with a fake engine.
        worker_factory: When given, a worker runs in a background thread for the app's
            lifetime (``sentinel serve --worker``, the default), so one process does everything.
        static_dir: Folder with the built web UI.
    """
    database = db or Database(settings.database_url)
    database.create_all()
    context = ApiContext(
        settings=settings,
        database=database,
        reviews=reviews or ReviewService(database, settings, public_url=settings.public_url),
        fixes=fixes or FixService(database, settings),
        static_dir=static_dir or STATIC_DIR,
    )
    app = FastAPI(title="Sentinel", version=__version__, lifespan=_lifespan(worker_factory))
    app.state.context = context
    if settings.auth_mode == LOCAL_AUTH_MODE:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    for router in API_ROUTERS:
        app.include_router(router)
    app.include_router(SPA_ROUTER)  # catch-all: must come last
    return app


def _lifespan(
    worker_factory: Callable[[], Any] | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Start an in-process worker thread on startup (if requested) and stop it on shutdown."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if worker_factory is None:
            yield
            return
        stop = threading.Event()
        worker = worker_factory()
        thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
        thread.start()
        yield
        stop.set()
        thread.join(timeout=WORKER_SHUTDOWN_SECONDS)

    return lifespan
