"""Golden regression tests.

Each directory in ``cases/`` holds a ``base/`` tree, a ``change/`` overlay, an optional
``ai.json`` (scripted model output — including deliberately wrong claims) and an
``expected.yaml`` describing what must be surfaced, what must be rejected, and what
must never reach the AI provider. A change to any analyzer, probe, prompt or scoring
rule that alters these outcomes fails here first.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from sentinel.analysis.diff.git import staged_changeset
from sentinel.bootstrap import build_orchestrator
from sentinel.core.configuration.config import Settings, load_repo_config
from sentinel.core.domain.models import Finding, ReviewResult
from sentinel.infrastructure.storage.cache import MemoryCache
from tests.fakes import ScriptedProvider

CASES = Path(__file__).parent / "cases"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "g",
    "GIT_AUTHOR_EMAIL": "g@e",
    "GIT_COMMITTER_NAME": "g",
    "GIT_COMMITTER_EMAIL": "g@e",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**GIT_ENV, "HOME": str(repo)},
    )


def _materialize(case: Path, dest: Path) -> Path:
    shutil.copytree(case / "base", dest)
    _git(dest, "init", "-q")
    _git(dest, "add", "-A", "-f")
    _git(dest, "commit", "-qm", "base")
    for item in (case / "change").rglob("*"):
        if item.is_file():
            target = dest / item.relative_to(case / "change")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    _git(dest, "add", "-A", "-f")
    return dest


def run_case(case: Path, tmp: Path) -> tuple[ReviewResult, ScriptedProvider | None]:
    repo = _materialize(case, tmp / case.name)
    ai_file = case / "ai.json"
    ai = ScriptedProvider(json.loads(ai_file.read_text())) if ai_file.exists() else None
    orch = build_orchestrator(
        Settings(provider="none"),
        load_repo_config(repo),
        workspace=repo,
        ai=ai,
        cache=MemoryCache(),
    )
    return orch.review(staged_changeset(repo), repo, repository=case.name), ai


def _matches(f: Finding, spec: dict[str, Any]) -> bool:
    if "tag" in spec and spec["tag"] not in f.tags:
        return False
    if "file" in spec and f.file != spec["file"]:
        return False
    if "line" in spec and not (f.line_start <= spec["line"] <= f.line_end):
        return False
    if "severity" in spec and f.severity.value != spec["severity"]:
        return False
    if "title_contains" in spec and spec["title_contains"] not in f.title:
        return False
    if "source" in spec and f.source.value != spec["source"]:
        return False
    if "verification" in spec:
        wanted = spec["verification"]
        wanted = wanted if isinstance(wanted, list) else [wanted]
        if f.verification is None or f.verification.status.value not in wanted:
            return False
    return True


def _describe(findings: list[Finding]) -> str:
    return "\n".join(
        f"  {f.title} | {f.location} | {f.severity.value} | tags={f.tags} | "
        f"{f.verification.status.value if f.verification else '-'} | {f.suppressed_reason or ''}"
        for f in findings
    )


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir() if p.is_dir()))
def test_golden(case: str, tmp_path: Path) -> None:
    root = CASES / case
    expected = yaml.safe_load((root / "expected.yaml").read_text())
    result, ai = run_case(root, tmp_path)
    context = (
        f"\nsurfaced:\n{_describe(result.findings)}\nsuppressed:\n{_describe(result.suppressed)}"
    )

    assert result.summary.risk.value == expected["risk"], context
    if expected.get("surfaced") == []:
        assert result.findings == [], context
    for spec in expected.get("surfaced") or []:
        assert any(_matches(f, spec) for f in result.findings), f"missing {spec}{context}"
    for spec in expected.get("suppressed") or []:
        assert any(_matches(f, spec) for f in result.suppressed), f"not suppressed {spec}{context}"
    for spec in expected.get("suppressed_or_surfaced") or []:
        assert any(_matches(f, spec) for f in result.all_findings()), f"missing {spec}{context}"
    for secret in expected.get("never_sent_to_ai") or []:
        if ai is not None:
            assert all(secret not in r.model_dump_json() for r in ai.requests)
        assert secret not in json.dumps(result.sources)
