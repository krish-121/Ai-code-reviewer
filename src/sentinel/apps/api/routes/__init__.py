"""HTTP routes, one module per resource. ``create_app`` registers them in this order."""

from fastapi import APIRouter

from sentinel.apps.api.routes import findings, github, reviews, system, web

API_ROUTERS: list[APIRouter] = [system.router, reviews.router, findings.router, github.router]

# The web UI's catch-all route; registered after every API router.
SPA_ROUTER: APIRouter = web.router
