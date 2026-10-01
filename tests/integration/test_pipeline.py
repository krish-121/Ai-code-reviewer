"""End-to-end review pipeline tests.

git diff -> context -> static -> AI (scripted) -> verification -> findings. No network, no real AI provider.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sentinel.analysis.diff.git import staged_changeset
from sentinel.bootstrap import build_orchestrator
from sentinel.core.configuration.config import RepoConfig, Settings, parse_repo_config
from sentinel.core.domain.models import (
    FindingSource,
    ReviewStatus,
    RiskLevel,
    StageName,
    StageRecord,
    StageStatus,
    VerificationStatus,
)
from sentinel.core.domain.ports import AIError
from sentinel.infrastructure.storage.cache import MemoryCache
from tests.fakes import ScriptedProvider, ai_finding
from tests.helpers import SHOP

SAFE_FIND_USER = (
    "    cur.execute(\n"
    '        "SELECT * FROM users WHERE name = ? AND password = ?", (name, password)\n'
    "    )\n"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The shop fixture where the *staged* change introduces the SQL injection + a secret."""
    root = tmp_path / "shop"
    shutil.copytree(SHOP, root, ignore=shutil.ignore_patterns("__pycache__", ".*cache"))
    db = root / "app" / "db.py"
    vulnerable = db.read_text()
    safe = vulnerable.replace(
        "    cur.execute(f\"SELECT * FROM users WHERE name = '{name}' AND password = '{password}'\")\n",
        SAFE_FIND_USER,
    )
    assert safe != vulnerable
    db.write_text(safe)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    db.write_text(vulnerable)
    (root / "app" / "settings.py").write_text('STRIPE_KEY = "sk_live_' + "a" * 24 + '"\n')
    (root / ".env").write_text("DB_PASSWORD=supersecret123\n")
    git(root, "add", "-A")
    return root


def settings() -> Settings:
    return Settings(provider="none")


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def stage_changed(self, stage: StageRecord) -> None:
        self.events.append((stage.name.value, stage.status.value))


def run(
    repo: Path,
    ai: ScriptedProvider | None,
    config: RepoConfig | None = None,
    progress: Recorder | None = None,
):  # type: ignore[no-untyped-def]
    cs = staged_changeset(repo)
    orch = build_orchestrator(
        settings(),
        config or RepoConfig(),
        workspace=repo,
        ai=ai,
        progress=progress,
        cache=MemoryCache(),
    )
    return orch.review(cs, repo, repository="shop")


AI_FINDINGS = [
    # 1. Real SQL injection -> should be SUPPORTED and merged with the static findings.
    ai_finding(
        category="security",
        severity="high",
        confidence=0.8,
        line=11,
        title="SQL injection in find_user",
        explanation="`name` and `password` are interpolated into the SQL string with an "
        "f-string. login() calls authenticate() which calls find_user() with form data.",
        evidence=["login() calls authenticate()", "authenticate() calls find_user()"],
        suggested_fix="Use placeholders.",
    ),
    # 2. False positive: the safe variant is parameterized -> REJECTED by the probe.
    ai_finding(
        category="security",
        severity="high",
        confidence=0.6,
        line=17,
        title="SQL injection in find_user_safe",
        explanation="The query in find_user_safe() may be vulnerable to SQL injection.",
    ),
    # 3. Hallucination: symbols and file that don't exist -> REJECTED.
    ai_finding(
        category="bug",
        severity="medium",
        confidence=0.7,
        file="app/auth_utils.py",
        line=4,
        title="sanitize_input() is bypassed",
        explanation="`sanitize_input()` is never called before `hash_password()`.",
    ),
    # 4. Test gap -> SUPPORTED: no test exercises find_user.
    ai_finding(
        category="tests",
        severity="medium",
        confidence=0.6,
        line=11,
        title="Changed query in find_user has no tests",
        explanation="find_user() changed but no test covers it.",
    ),
    # 5. Style remark disguised as a bug -> REJECTED (style is opt-in).
    ai_finding(
        category="bug",
        severity="low",
        confidence=0.5,
        line=9,
        title="Variable naming: rename cur to cursor",
        explanation="Use descriptive variable names.",
    ),
]


def test_full_pipeline_verifies_and_rejects(repo: Path) -> None:
    progress = Recorder()
    ai = ScriptedProvider(AI_FINDINGS)
    result = run(repo, ai, progress=progress)

    assert result.status is ReviewStatus.COMPLETED, result.errors
    assert [s.status for s in result.stages] == [StageStatus.DONE] * len(result.stages)
    assert ("ai_review", "running") in progress.events
    assert result.usage.input_tokens == 1200

    surfaced = {f.title: f for f in result.findings}
    suppressed = {f.title: f for f in result.suppressed}

    sqli = surfaced["SQL injection in find_user"]
    assert sqli.source is FindingSource.COMBINED
    assert sqli.verification is not None
    assert sqli.verification.status is VerificationStatus.SUPPORTED
    assert sqli.verification.reachability == "entrypoint"
    assert sqli.verification.call_path[0] == "POST /login"
    assert any(o.startswith("ruff:") for o in sqli.origins)
    assert any(o.startswith("sentinel:sql-injection") for o in sqli.origins)
    checks = {c.name: c for c in sqli.verification.checks}
    assert checks["probe:sql-injection"].outcome.value == "supports"
    assert checks["call-path"].outcome.value == "supports"

    fp = suppressed["SQL injection in find_user_safe"]
    assert fp.verification and fp.verification.status is VerificationStatus.REJECTED
    assert "parameterized" in fp.verification.summary

    halluc = suppressed["sanitize_input() is bypassed"]
    assert halluc.verification and halluc.verification.status is VerificationStatus.REJECTED
    assert "does not exist" in halluc.verification.summary

    gap = surfaced["Changed query in find_user has no tests"]
    assert gap.verification and gap.verification.status is VerificationStatus.SUPPORTED

    style = suppressed["Variable naming: rename cur to cursor"]
    assert style.verification and style.verification.status is VerificationStatus.REJECTED

    # Deterministic findings from filtering: the committed .env and the Stripe key.
    assert any(f.file == ".env" for f in result.findings)
    stripe = next(f for f in result.findings if f.file == "app/settings.py")
    assert "secret" in stripe.tags and "sk_live" not in stripe.model_dump_json().replace(
        "sk_live_****", ""
    )

    # N+1 in services.py is pre-existing (not changed) -> not surfaced.
    assert all("N+1" not in f.title for f in result.findings)

    # Secrets never reached the AI.
    sent = ai.requests[0]
    assert "a" * 24 not in sent.diff
    assert ".env" not in [b.file for b in sent.context]
    assert "supersecret123" not in sent.model_dump_json()
    assert any(b.kind == "caller" and b.symbol == "authenticate" for b in sent.context)

    summary = result.summary
    assert summary.risk is RiskLevel.HIGH
    assert summary.stats.by_severity["high"] >= 2
    assert any("Rejected 3" in v for v in summary.verified)
    assert result.graph and any(n["meta"].get("changed") for n in result.graph["nodes"])
    assert "app/db.py" in result.sources
    assert "a" * 24 not in result.sources.get("app/settings.py", "")
    fingerprints = [f.fingerprint for f in result.findings]
    assert all(fingerprints) and len(set(fingerprints)) == len(fingerprints)


def test_ai_failure_degrades_to_partial(repo: Path) -> None:
    result = run(repo, ScriptedProvider(error=AIError("HTTP 500: boom")))
    assert result.status is ReviewStatus.PARTIAL
    ai_stage = next(s for s in result.stages if s.name is StageName.AI_REVIEW)
    assert ai_stage.status is StageStatus.FAILED and "boom" in ai_stage.detail
    # deterministic findings still present
    assert any("SQL" in f.title for f in result.findings)


def test_no_provider_is_deterministic_only(repo: Path) -> None:
    result = run(repo, None)
    assert result.status is ReviewStatus.COMPLETED
    ai_stage = next(s for s in result.stages if s.name is StageName.AI_REVIEW)
    assert ai_stage.status is StageStatus.SKIPPED
    assert any("AI review skipped" in u for u in result.summary.uncertain)
    sqli = next(f for f in result.findings if "SQL" in f.title)
    assert sqli.is_deterministic and sqli.source is FindingSource.COMBINED


def test_config_threshold_and_budget(repo: Path) -> None:
    cfg = parse_repo_config("severity_threshold: high\nreview:\n  max_findings: 1\n")
    result = run(repo, ScriptedProvider(AI_FINDINGS), cfg)
    assert len(result.findings) == 1
    assert result.findings[0].severity.value == "high"
    reasons = {f.suppressed_reason or "" for f in result.suppressed}
    assert any("below severity threshold" in r for r in reasons)
    assert any("display budget" in r for r in reasons)


def test_crashing_stage_is_contained(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sentinel.core.review.orchestrator as orch_mod

    def boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(orch_mod, "build_graph", boom)
    result = run(repo, None)
    graph_stage = next(s for s in result.stages if s.name is StageName.BUILD_GRAPH)
    assert graph_stage.status is StageStatus.FAILED
    assert result.status is ReviewStatus.PARTIAL
    assert result.findings  # static analysis still ran


def test_empty_change(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q")
    result = run(root, ScriptedProvider([]))
    assert result.status is ReviewStatus.COMPLETED
    assert result.findings == []
    assert result.summary.risk is RiskLevel.NONE
    assert result.summary.headline == "No problems found in this change"
