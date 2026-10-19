"""Wire the public demo to scripted replies and ordinary Sentinel services.

The seed and server scripts share this small composition root. It never loads user
settings or contacts an AI service; analysis, verification, storage and Docker fix
validation still use the production implementations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from sentinel.bootstrap import build_fix_engine
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.ai import (
    AIFixPayload,
    AIFixResult,
    AIReviewPayload,
    AIReviewResult,
    FixRequest,
    ReviewRequest,
)
from sentinel.core.domain.ports import AIError
from sentinel.core.fixes.engine import FixEngine
from sentinel.infrastructure.database.session import Database
from sentinel.services.fixes import FixService
from sentinel.services.reviews import ReviewService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT / ".demo" / "sentinel-demo"
DEFAULT_DB = ROOT / ".demo" / "sentinel-demo.db"
DEMO_BRANCH = "feature/search-and-reports"
TARGET_FILE = "app/db.py"


class ReplayProvider:
    """Return visibly scripted example replies, with zero billable token usage."""

    name = "replay"
    model = "scripted-demo"

    def __init__(self) -> None:
        data = json.loads((ROOT / "scripts/demo_ai_responses.json").read_text(encoding="utf-8"))
        self.review_payload = AIReviewPayload.model_validate({"findings": data["review"]})
        self.fix_payload = AIFixPayload.model_validate(data["fix"])

    def review(self, request: ReviewRequest) -> AIReviewResult:
        """Replay the planted claims; this is not an assessment of arbitrary code."""
        return AIReviewResult(
            payload=self.review_payload.model_copy(deep=True), model=self.model, provider=self.name
        )

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        """Offer only the supplied search-products SQL fix, never a general AI fix."""
        if request.file != TARGET_FILE or self.fix_payload.edits[0].search not in request.files.get(
            TARGET_FILE, ""
        ):
            raise AIError("The scripted demo fixes only the original search_products SQL issue.")
        return AIFixResult(
            payload=self.fix_payload.model_copy(deep=True), model=self.model, provider=self.name
        )


def demo_settings(
    database: Path,
    repository: Path,
    *,
    transport: Literal["bind", "copy"] = "copy",
    image: str = "sentinel-sandbox:latest",
) -> Settings:
    """Isolate demo data and local access without reading saved keys or environment settings."""
    return Settings(
        provider="none",
        database_url=f"sqlite:///{database.resolve()}",
        cache_dir=database.resolve().parent / "demo-cache",
        auth_mode="local",
        local_roots=str(repository.resolve()),
        sandbox_transport=transport,
        sandbox_image=image,
    )


def demo_services(settings: Settings) -> tuple[Database, ReviewService, FixService]:
    """Reuse the real review/fix services, injecting replay only at the provider boundary."""
    database = Database(settings.database_url)
    database.create_all()
    reviews = ReviewService(database, settings, ai_factory=ReplayProvider)

    def engine_factory(root: Path, trusted: bool) -> FixEngine:
        return build_fix_engine(
            settings,
            load_repo_config(root),
            workspace=root,
            ai=ReplayProvider(),
            trusted_workspace=trusted,
        )

    return database, reviews, FixService(database, settings, engine_factory=engine_factory)
