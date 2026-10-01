from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
from sentinel.core.configuration.config import load_repo_config
from sentinel.core.domain.ai import FileEdit
from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from sentinel.core.domain.ports import AIError, SandboxResult
from sentinel.core.fixes.engine import ApplyError, FixEngine, FixOutcome, apply_fix
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256, unified_diff
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.core.fixes.validation import detect_test_command, python_syntax
from sentinel.sandbox.runners import ProcessSandbox
from tests.fakes import ScriptedProvider

DEMO = Path(__file__).resolve().parents[2] / "demo" / "build_demo_repo.py"
VULN = "    query = f\"SELECT id, name, price FROM products WHERE name LIKE '%{term}%' ORDER BY name\"\n    return conn.execute(query).fetchall()\n"
FIXED = (
    '    query = "SELECT id, name, price FROM products WHERE name LIKE ? ORDER BY name"\n'
    '    return conn.execute(query, (f"%{term}%",)).fetchall()\n'
)


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    sys.path.insert(0, str(DEMO.parent))
    try:
        import build_demo_repo

        return build_demo_repo.build(tmp_path / "demo")
    finally:
        sys.path.remove(str(DEMO.parent))


def sqli_finding() -> Finding:
    return Finding(
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.9,
        title="SQL injection in search_products",
        explanation="term is interpolated",
        file="app/db.py",
        line_start=34,
        line_end=35,
        source=FindingSource.COMBINED,
        origins=["ai:x", "sentinel:sql-injection"],
        tags=["sql-injection"],
    )


def fix_payload(search: str, replace: str) -> dict[str, object]:
    return {
        "summary": "Use a parameterized LIKE query",
        "edits": [{"file": "app/db.py", "search": search, "replace": replace}],
    }


class FakeSandbox:
    isolation = "fake"

    def __init__(self, *results: SandboxResult, available: bool = True) -> None:
        self.results = list(results)
        self.available = available
        self.commands: list[tuple[Path, list[str]]] = []

    def is_available(self) -> bool:
        return self.available

    def run(self, workspace: Path, command: list[str], timeout_s: int = 120) -> SandboxResult:
        self.commands.append((workspace, command))
        return self.results.pop(0)


def ok(code: int = 0, out: str = "") -> SandboxResult:
    return SandboxResult(command=[], exit_code=code, stdout=out, stderr="", duration_ms=5)


def engine(ai: ScriptedProvider, sandbox: object, root: Path) -> FixEngine:
    registry = default_registry()
    return FixEngine(
        ai,
        static_runner=StaticAnalysisRunner(default_analyzers(registry), disabled=["mypy"]),
        sandbox=sandbox,  # type: ignore[arg-type]
        config=load_repo_config(root),
    )


# ----------------------------------------------------------------- patch primitives


def test_apply_edits_rules() -> None:
    files = {"a.py": "x = 1\ny = 2\nx = 1\n"}
    out = apply_edits(files, [FileEdit(file="a.py", search="y = 2", replace="y = 3")])
    assert out == {"a.py": "x = 1\ny = 3\nx = 1\n"}
    with pytest.raises(PatchError, match="occurs 2 times"):
        apply_edits(files, [FileEdit(file="a.py", search="x = 1", replace="z")])
    with pytest.raises(PatchError, match="closest existing line"):
        apply_edits(files, [FileEdit(file="a.py", search="y  = 2", replace="z")])
    with pytest.raises(PatchError, match="not one of the files"):
        apply_edits(files, [FileEdit(file="other.py", search="x", replace="z")])
    with pytest.raises(PatchError, match="redacted"):
        apply_edits(files, [FileEdit(file="a.py", search="[REDACTED:x]", replace="z")])
    with pytest.raises(PatchError, match="empty"):
        apply_edits(files, [FileEdit(file="a.py", search="", replace="z")])
    diff = unified_diff(files, out)
    assert diff.startswith("diff --git a/a.py b/a.py") and "-y = 2" in diff and "+y = 3" in diff
    assert unified_diff(files, files) == ""


def test_python_syntax_and_test_detection(tmp_path: Path) -> None:
    assert python_syntax("a.py", "def f(:\n") is not None
    assert python_syntax("a.py", "x = 1\n") is None
    assert python_syntax("a.ts", "def f(:") is None
    cfg = load_repo_config(tmp_path)
    assert detect_test_command(tmp_path, cfg) is None
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run"}}')
    assert detect_test_command(tmp_path, cfg) == ["npm", "test", "--silent"]
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "echo \\"Error: no test specified\\""}}'
    )
    assert detect_test_command(tmp_path, cfg) is None
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("")
    assert detect_test_command(tmp_path, cfg)[:3] == ["python", "-m", "pytest"]  # type: ignore[index]


def test_scratch_copy_skips_git_and_links_deps(tmp_path: Path) -> None:
    root = tmp_path / "r"
    (root / ".git").mkdir(parents=True)
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x")
    (root / "top.txt").write_text("t")
    copy = scratch_copy(root)
    try:
        assert not (copy / ".git").exists()
        assert (copy / "node_modules").is_symlink()
        assert (copy / "src" / "a.py").read_text() == "x"
        assert (copy / "top.txt").exists()
    finally:
        shutil.rmtree(copy)


# ----------------------------------------------------------------- fix engine


def test_fix_validated_with_tests_and_deterministic_recheck(demo: Path) -> None:
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
    sandbox = FakeSandbox(ok(), ok(out="2 passed"))
    outcome = engine(ai, sandbox, demo).generate(sqli_finding(), demo)
    assert outcome.status == "validated", outcome.checks
    checks = {c.name: c for c in outcome.checks}
    assert checks["finding-resolved"].status == "passed"
    assert "sentinel/sql-injection" in checks["finding-resolved"].detail
    assert checks["no-new-issues"].status == "passed"
    assert checks["tests"].status == "passed"
    assert len(sandbox.commands) == 2  # baseline + patched
    assert "pytest" in sandbox.commands[0][1]
    assert outcome.patch.startswith("diff --git a/app/db.py")
    assert outcome.original_hashes["app/db.py"] == sha256((demo / "app/db.py").read_text())
    # the real repository was not touched
    assert "LIKE '%{term}%'" in (demo / "app/db.py").read_text()
    written = apply_fix(demo, outcome)
    assert written == ["app/db.py"]
    assert "LIKE ?" in (demo / "app/db.py").read_text()
    with pytest.raises(ApplyError, match="changed since"):
        apply_fix(demo, outcome)


def test_bad_patch_is_retried_with_feedback(demo: Path) -> None:
    ai = ScriptedProvider(
        fixes=[fix_payload("this text is not in the file", "x"), fix_payload(VULN, FIXED)]
    )
    outcome = engine(ai, FakeSandbox(available=False), demo).generate(sqli_finding(), demo)
    assert outcome.attempts == 2
    assert ai.fix_requests[1].feedback is not None
    assert "not found" in ai.fix_requests[1].feedback
    assert outcome.status == "validated"  # deterministic re-check passed, tests skipped
    tests = next(c for c in outcome.checks if c.name == "tests")
    assert tests.status == "skipped" and "no sandbox" in tests.detail


def test_patch_that_breaks_tests_fails(demo: Path) -> None:
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED), fix_payload(VULN, FIXED)])
    failing = SandboxResult(
        command=[], exit_code=1, stdout="FAILED test_x\n1 failed", stderr="", duration_ms=3
    )
    sandbox = FakeSandbox(ok(), failing, ok(), failing)
    outcome = engine(ai, sandbox, demo).generate(sqli_finding(), demo)
    assert outcome.status == "failed"
    assert "tests fail after the patch" in next(
        c.detail for c in outcome.checks if c.name == "tests"
    )
    assert ai.fix_requests[1].feedback and "tests" in ai.fix_requests[1].feedback


def test_patch_that_introduces_issues_or_breaks_syntax(demo: Path) -> None:
    worse = VULN + "    eval(term)\n"
    ai = ScriptedProvider(fixes=[fix_payload(VULN, "    return (\n"), fix_payload(VULN, worse)])
    outcome = engine(ai, FakeSandbox(available=False), demo).generate(sqli_finding(), demo)
    assert ai.fix_requests[1].feedback and "syntax" in ai.fix_requests[1].feedback
    assert outcome.status == "failed"
    failed = {c.name for c in outcome.checks if c.status == "failed"}
    assert {"finding-resolved", "no-new-issues"} <= failed


def test_baseline_failures_are_not_blamed_on_the_patch(demo: Path) -> None:
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
    sandbox = FakeSandbox(ok(code=1))
    outcome = engine(ai, sandbox, demo).generate(sqli_finding(), demo)
    tests = next(c for c in outcome.checks if c.name == "tests")
    assert tests.status == "skipped" and "already fail" in tests.detail


def test_unverifiable_fix_and_errors(demo: Path) -> None:
    finding = sqli_finding().model_copy(
        update={"tags": [], "origins": ["ai:x"], "title": "Rename search"}
    )
    ai = ScriptedProvider(fixes=[fix_payload(VULN, VULN.replace("query", "sql"))])
    outcome = engine(ai, FakeSandbox(available=False), demo).generate(finding, demo)
    assert outcome.status == "unverified"
    err = engine(ScriptedProvider(fixes=[AIError("quota")]), None, demo).generate(finding, demo)
    assert err.status == "error" and err.error == "quota"
    missing = finding.model_copy(update={"file": "nope.py"})
    assert engine(ScriptedProvider(), None, demo).generate(missing, demo).status == "error"
    with pytest.raises(ApplyError, match="refusing"):
        apply_fix(demo, FixOutcome(status="failed"))


def test_process_sandbox_runs_real_tests(demo: Path) -> None:
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
    outcome = engine(ai, ProcessSandbox(), demo).generate(sqli_finding(), demo)
    tests = next(c for c in outcome.checks if c.name == "tests")
    assert tests.status == "passed", tests.detail
    assert outcome.isolation.startswith("process")
