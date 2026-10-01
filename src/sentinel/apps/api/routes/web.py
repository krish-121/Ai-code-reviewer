"""Serves the built web UI (``web/`` → ``apps/api/static``) as a single-page app.

Any path that is not an API route and not a real static file gets ``index.html``, so the
browser's client-side router can handle URLs such as ``/reviews/R-123``. This router must
be registered last because its catch-all path would otherwise shadow other routes.
"""

# No `from __future__ import annotations`: FastAPI evaluates route signatures.

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse

from sentinel.apps.api.dependencies import ContextDep

router = APIRouter(include_in_schema=False)

API_PREFIX = "api/"
NOT_BUILT_MESSAGE = "Sentinel API is running. Build the web UI with `npm run build` in web/."


@router.get("/{full_path:path}")
def single_page_app(full_path: str, context: ContextDep) -> Response:
    """Return a static asset if it exists, otherwise the app's ``index.html``."""
    if full_path.startswith(API_PREFIX):
        raise HTTPException(status_code=404)
    root = context.static_dir.resolve()
    candidate = (root / full_path).resolve()
    if full_path and candidate.is_file() and candidate.is_relative_to(root):
        return FileResponse(candidate)
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return PlainTextResponse(NOT_BUILT_MESSAGE, status_code=200)
