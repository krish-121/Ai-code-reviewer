"""Check free DeepSeek through Sentinel's authenticated local OpenCode bridge.

Run from the installed project: ``python scripts/check_free_models.py``. No keys,
local source files or billing account are sent. Results distinguish an HTTP outage
from a valid structured review; a failure is not proof that a top-up is required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sentinel.ai.providers.factory import create_provider
from sentinel.ai.providers.opencode import FREE_MODELS, OPENCODE_URL
from sentinel.core.configuration.config import load_settings
from sentinel.core.domain.ai import ReviewRequest
from sentinel.core.domain.models import Category
from sentinel.core.domain.ports import AIError


def check(model: str) -> dict[str, Any]:
    """Try one bounded request and report its actual outcome without any secrets."""
    settings = load_settings(
        overrides={
            "provider": "opencode",
            "model": model,
            "free_fallback": False,
            "max_retries": 0,
            "timeout_s": 90,
        }
    )
    provider = create_provider(settings)
    assert provider is not None
    request = ReviewRequest(
        review_id="public-free-access-check",
        repository="synthetic-example",
        changed_files=["average.py"],
        diff="--- /dev/null\n+++ b/average.py\n@@ -0,0 +1,2 @@\n"
        "+def average(values):\n+    return sum(values) / len(values)\n",
        categories=[Category.BUG],
        max_findings=2,
    )
    evidence: dict[str, Any] = {"model": model, "vendor_credentials_shared": False}
    started = monotonic()
    try:
        result = provider.review(request)
        evidence.update(status="success", result=result.model_dump(mode="json"))
    except AIError as exc:
        evidence.update(status="failed", error=str(exc))
    finally:
        evidence["elapsed_seconds"] = round(monotonic() - started, 3)
        provider.close()
    return evidence


if __name__ == "__main__":
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "endpoint": OPENCODE_URL,
        "checks": [check(model) for model in FREE_MODELS],
    }
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if all(item["status"] == "success" for item in report["checks"]) else 1)
