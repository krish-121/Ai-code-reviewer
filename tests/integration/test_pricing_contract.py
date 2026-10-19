"""Replay actual pricing proposals with the same stronger tests, without an AI call.

The old proposal repaired checkout but broke a public helper. Holding the generated
helper/caller tests constant distinguishes it from the later root-cause repair.
Only the ordinary fix engine decides the result; no evaluation-only rejection is added.
"""

import json
import os
from pathlib import Path

import pytest
from scripts import prepare_quality_case as examples

from sentinel.bootstrap import build_fix_engine, build_sandbox
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.ai import FileEdit
from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from sentinel.core.fixes.patch import apply_edits
from tests.fakes import ScriptedProvider

PAIR = examples.CASES.parent / "regressions/pricing_patch_pair.json"


@pytest.mark.docker
@pytest.mark.parametrize("proposal", ["old_edits", "fixed_edits"])
def test_pricing_fix_preserves_helper_and_checkout_contracts(tmp_path: Path, proposal: str) -> None:
    settings = Settings(
        provider="none",
        sandbox_image=os.environ.get("SENTINEL_TEST_SANDBOX_IMAGE", "sentinel-sandbox:latest"),
        sandbox_transport="copy" if os.environ.get("SENTINEL_TEST_DOCKER_COPY") == "1" else "bind",
    )
    sandbox = build_sandbox(settings)
    if sandbox is None or not sandbox.is_available():
        pytest.skip("docker daemon or sentinel-sandbox image unavailable")
    root = tmp_path / "case-01"
    examples.prepare_case("python_multifile_checkout", root)
    before = {
        path.relative_to(root).as_posix(): path.read_text()
        for folder in (root / "app", root / "tests")
        for path in folder.glob("*.py")
    }
    pair = json.loads(PAIR.read_text())
    test = FileEdit.model_validate(pair["regression_test"])
    edits = [FileEdit.model_validate(edit) for edit in pair[proposal]] + [test]
    after = apply_edits(before, edits, [test.file])
    finding = Finding(
        category=Category.BUG,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="quote_cart stores major-unit amounts as minor units",
        explanation="The pricing helper divides minor units before quote_cart consumes them.",
        file="app/service.py",
        line_start=8,
        line_end=8,
        source=FindingSource.AI,
        origins=["ai:captured"],
    )
    engine = build_fix_engine(
        settings, load_repo_config(root), workspace=root, ai=ScriptedProvider(), sandbox=sandbox
    )

    outcome = engine.validate(finding, root, before, after)

    checks = {check.name: check for check in outcome.checks}
    if proposal == "old_edits":
        assert outcome.status == "failed", outcome.checks
        assert checks["regression-tests"].status == "failed"
        assert checks["tests"].status == "failed"
    else:
        assert outcome.status == "validated", outcome.checks
        assert checks["regression-tests"].status == "passed"
    # Validation uses copies. Neither proposal may change the original example.
    assert (root / "app/pricing.py").read_text() == before["app/pricing.py"]
    assert not (root / test.file).exists()
