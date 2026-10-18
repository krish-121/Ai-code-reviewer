#!/usr/bin/env python3
"""Populate a Sentinel database with a review of the demo repository — no API key needed.

    python scripts/seed_demo.py                      # writes .demo/sentinel-demo.db
    SENTINEL_DATABASE_URL=sqlite:///.demo/sentinel-demo.db sentinel serve

The AI step is a *replay* of the scripted responses in ``demo_ai_responses.json`` (see
the note inside that file). Everything else — diff parsing, code graph, static analysis,
verification, deduplication, prioritization, the fix sandbox — runs for real. With a
provider configured, run ``sentinel review`` in the demo repository instead.

The fix's tests run in Docker (``sentinel-sandbox`` image, see Dockerfile.sandbox). Without
Docker the fix is reported as *unverified*. Generated-code analysis and tests require
Docker; the process sandbox is never used for fix validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

import build_demo_repo  # noqa: E402

from sentinel.bootstrap import build_fix_engine  # noqa: E402
from sentinel.core.configuration.config import Settings, load_repo_config  # noqa: E402
from sentinel.core.domain.ai import (  # noqa: E402
    AIFixPayload,
    AIFixResult,
    AIReviewPayload,
    AIReviewResult,
    FixRequest,
    ReviewRequest,
)
from sentinel.core.domain.models import TokenUsage  # noqa: E402
from sentinel.core.fixes.engine import FixEngine  # noqa: E402
from sentinel.infrastructure.database.session import Database  # noqa: E402
from sentinel.infrastructure.database.store import Store  # noqa: E402
from sentinel.services.fixes import FixService  # noqa: E402
from sentinel.services.reviews import ReviewService  # noqa: E402
from sentinel.services.workspaces import LocalRequest  # noqa: E402


class ReplayProvider:
    """Replays scripted model output. For offline demos only; not a real reviewer."""

    name = "replay"
    model = "scripted-demo"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def review(self, request: ReviewRequest) -> AIReviewResult:
        """Return the scripted review findings (token usage is estimated from the prompt)."""
        payload = AIReviewPayload.model_validate({"findings": self.data["review"]})
        tokens = len(request.diff + "".join(b.code for b in request.context)) // 4
        return AIReviewResult(
            payload=payload,
            model=self.model,
            provider=self.name,
            usage=TokenUsage(input_tokens=tokens, output_tokens=900),
        )

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        """Return the scripted SQL-injection fix."""
        return AIFixResult(
            payload=AIFixPayload.model_validate(self.data["fix"]),
            model=self.model,
            provider=self.name,
            usage=TokenUsage(input_tokens=1400, output_tokens=160),
        )


def main() -> None:
    """Build the demo repository, review it, and generate + validate one fix."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / ".demo" / "sentinel-demo.db"))
    parser.add_argument("--repo", default=str(ROOT / ".demo" / "sentinel-demo"))
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    repo = build_demo_repo.build(Path(args.repo))
    settings = Settings(
        provider="none",
        database_url=f"sqlite:///{Path(args.db).resolve()}",
    )
    db = Database(settings.database_url)
    db.create_all()
    replay = ReplayProvider(json.loads((ROOT / "scripts" / "demo_ai_responses.json").read_text()))

    reviews = ReviewService(db, settings, ai_factory=lambda: replay)
    review_id = reviews.create_local(
        "local",
        LocalRequest(path=str(repo), mode="range", base="main", head="feature/search-and-reports"),
        enqueue=False,
    )
    result = reviews.run(review_id)
    print(f"review {review_id}: {result.summary.headline}")

    def engine_factory(root: Path, trusted: bool) -> FixEngine:
        return build_fix_engine(
            settings,
            load_repo_config(root),
            workspace=root,
            ai=replay,
            trusted_workspace=trusted,
        )

    target = next(f for f in result.findings if f.file == "app/db.py" and "sql-injection" in f.tags)
    with db.transaction() as s:
        store = Store(s)
        row = store.finding_for(store.local_user(), target.id)
        assert row is not None
        fix_id = store.create_fix(row).id
    outcome = FixService(db, settings, engine_factory=engine_factory).run(fix_id)
    print(f"fix {fix_id} for {target.id}: {outcome.status} (isolation: {outcome.isolation})")


if __name__ == "__main__":
    main()
