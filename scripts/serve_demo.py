#!/usr/bin/env python3
"""Open the seeded public demo locally, with scripted AI and a real background worker.

Run after seed_demo.py. No user configuration, model service, GitHub access or API
key is used. The server can review only the selected sample repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn
from demo_support import DEFAULT_DB, DEFAULT_REPO, demo_services, demo_settings

from sentinel.apps.api.app import create_app
from sentinel.apps.worker.main import Worker


def main() -> None:
    """Serve the ordinary UI and queue on loopback, keeping the owner's app untouched."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--port", type=int, default=8820)
    parser.add_argument("--transport", choices=("copy", "bind"), default="copy")
    parser.add_argument("--image", default="sentinel-sandbox:latest")
    args = parser.parse_args()
    if not args.db.is_file() or not (args.repo / ".git").is_dir():
        parser.error("Run python scripts/seed_demo.py first, using the same --db and --repo.")
    receipt_path = args.db.with_suffix(".receipt.json")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        valid = (
            isinstance(receipt, dict)
            and receipt.get("mode") == "scripted-replay-no-api"
            and Path(receipt["repository"]).resolve() == args.repo.resolve()
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        parser.error(
            "The selected database/repository do not have a matching scripted-demo receipt."
        )
    settings = demo_settings(args.db, args.repo, transport=args.transport, image=args.image)
    database, reviews, fixes = demo_services(settings)
    app = create_app(
        settings,
        db=database,
        reviews=reviews,
        fixes=fixes,
        worker_factory=lambda: Worker(database, reviews, fixes, kinds=("review", "fix")),
    )
    print(f"SCRIPTED DEMO — no live model or API calls. Open http://127.0.0.1:{args.port}")
    print(f"Sample repository: {args.repo.resolve()}")
    print("Only the supplied search_products SQL fix is scripted. Ctrl+C stops this demo.")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
