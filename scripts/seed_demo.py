#!/usr/bin/env python3
"""Prepare a public sample review and a Docker-validated scripted fix without API keys.

Run from the checkout after installation and building Dockerfile.sandbox. Follow
with python scripts/serve_demo.py. A JSON receipt records the actual results; failed
or missing validation never counts as a successful demo. Nothing is auto-applied.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from demo_support import (
    DEFAULT_DB,
    DEFAULT_REPO,
    DEMO_BRANCH,
    ROOT,
    TARGET_FILE,
    demo_services,
    demo_settings,
)

from sentinel.bootstrap import build_sandbox
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import Category, ReviewResult, ReviewStatus, VerificationStatus
from sentinel.infrastructure.database.session import Database
from sentinel.infrastructure.database.store import Store
from sentinel.services.fixes import FixService
from sentinel.services.workspaces import LocalRequest

# The sample builder is checkout tooling rather than part of the installed package.
sys.path.insert(0, str(ROOT / "demo"))
import build_demo_repo


def validate_fix(database: Database, fixes: FixService, result: ReviewResult) -> dict[str, object]:
    """Generate the target proposal without applying it, retaining every real check."""
    target = next(
        (
            finding
            for finding in result.findings
            if finding.file == TARGET_FILE
            and "sql-injection" in finding.tags
            and finding.verification is not None
            and finding.verification.status == VerificationStatus.SUPPORTED
        ),
        None,
    )
    if target is None:
        return {"fix_passed": False, "fix_error": "No supported sample SQL finding was available."}
    with database.transaction() as session:
        store = Store(session)
        row = store.finding_for(store.local_user(), target.id)
        assert row is not None
        fix_id = store.create_fix(row).id
    outcome = fixes.run(fix_id)
    print(f"Scripted fix {fix_id}: {outcome.status}; isolation: {outcome.isolation}")
    return {
        "finding_id": target.id,
        "fix_id": fix_id,
        "fix": outcome.model_dump(mode="json"),
        "fix_passed": outcome.status == "validated"
        and all(c.status == "passed" for c in outcome.checks),
    }


def seed(repository: Path, settings: Settings, *, review_only: bool) -> dict[str, object]:
    """Run the sample and classify acceptance using actual results, never hard-coded verdicts."""
    database, reviews, fixes = demo_services(settings)
    review_id = reviews.create_local(
        "local",
        LocalRequest(path=str(repository), mode="range", base="main", head=DEMO_BRANCH),
        enqueue=False,
    )
    result = reviews.run(review_id)
    categories = {finding.category.value for finding in result.findings}
    receipt: dict[str, object] = {
        "mode": "scripted-replay-no-api",
        "review_id": review_id,
        "review_status": result.status.value,
        "repository": str(repository),
        "categories": sorted(categories),
        "suppressed": [finding.title for finding in result.suppressed],
        "rejected": [
            finding.title
            for finding in result.suppressed
            if finding.verification is not None
            and finding.verification.status == VerificationStatus.REJECTED
        ],
        "errors": result.errors,
        "auto_applied": False,
    }
    print(f"SCRIPTED DEMO review {review_id}: {result.status.value}")
    print(result.summary.headline)
    if not review_only:
        receipt.update(validate_fix(database, fixes, result))
    required = {
        Category.BUG.value,
        Category.SECURITY.value,
        Category.PERFORMANCE.value,
        Category.TESTS.value,
    }
    receipt["complete"] = (
        result.status == ReviewStatus.COMPLETED
        and required.issubset(categories)
        and bool(receipt["rejected"])
        and bool(receipt.get("fix_passed"))
    )
    return receipt


def main() -> None:
    """Create an exclusive sample, run review/validation, and save a portable result receipt."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--transport", choices=("copy", "bind"), default="copy")
    parser.add_argument("--image", default="sentinel-sandbox:latest")
    parser.add_argument(
        "--review-only", action="store_true", help="Skip fix validation; no Docker needed"
    )
    args = parser.parse_args()
    paths = (args.db, args.repo, args.db.with_suffix(".receipt.json"))
    if any(path.exists() or path.is_symlink() for path in paths):
        parser.error(
            "Demo paths already exist. Reopen with serve_demo.py, or choose NEW --repo/--db paths."
        )
    settings = demo_settings(args.db, args.repo, transport=args.transport, image=args.image)
    if not args.review_only and build_sandbox(settings) is None:
        parser.error("Docker/image unavailable. Build Dockerfile.sandbox, or select --review-only.")
    repository = build_demo_repo.build(args.repo.resolve())
    args.db.parent.mkdir(parents=True, exist_ok=True)
    receipt = seed(repository, settings, review_only=args.review_only)
    receipt_path = args.db.with_suffix(".receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Receipt: {receipt_path.resolve()}")
    print("Open the UI: python scripts/serve_demo.py (repeat custom --repo/--db if supplied).")
    if not args.review_only and not receipt["complete"]:
        raise SystemExit(
            "Demo acceptance did not complete. Inspect the receipt; no files were applied."
        )


if __name__ == "__main__":
    main()
