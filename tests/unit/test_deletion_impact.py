"""S16: compare base/head evidence across the whole eligible source tree."""

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.graph.deletion import broken_imports
from sentinel.analysis.static.base import static_finding
from sentinel.bootstrap import default_verifier
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import (
    AnalysisRun,
    Category,
    ChangeSet,
    ChangeType,
    FileChange,
    Severity,
)
from sentinel.core.findings.dedup import merge
from sentinel.core.review.baseline import compare_diagnostics
from sentinel.core.review.orchestrator import ReviewOrchestrator
from tests.fakes import ScriptedProvider

DELETE = "diff --git a/dep.py b/dep.py\ndeleted file mode 100644\n--- a/dep.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-VALUE = 42\n"


def diagnostic(file="caller.py", line=2, title="Undefined name", rule="F821"):
    return static_finding(
        tool="ruff",
        rule=rule,
        category=Category.BUG,
        severity=Severity.HIGH,
        confidence=0.95,
        title=title,
        file=file,
        line=line,
    )


def trees(tmp_path, before, after):
    roots = [tmp_path / "base", tmp_path / "head"]
    for root, files in zip(roots, (before, after), strict=True):
        root.mkdir()
        for path, text in files.items():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)
    return roots


class Runner:
    def __init__(self, before=(), after=(), base_status="ok", head_status="ok"):
        self.before, self.after = before, after
        self.base_status, self.head_status = base_status, head_status
        self.calls = []

    def run(self, root, files):
        self.calls.append((root.name, set(files)))
        baseline = root.name == "base"
        findings = self.before if baseline else self.after
        status = self.base_status if baseline else self.head_status
        return [f.model_copy(deep=True) for f in findings], [
            AnalysisRun(tool="ruff", status=status)
        ]


def review(base, head, runner, *, config=None, max_files=2000, change=None):
    ai = ScriptedProvider()
    engine = ReviewOrchestrator(
        extractor=default_registry(),
        static_runner=runner,
        verifier=default_verifier(),
        ai=ai,
        config=config,
        max_graph_files=max_files,
    )
    return engine.review(change or parse_unified_diff(DELETE), head, baseline=base), ai


def test_unchanged_and_transitive_callers_are_scanned_and_new_diagnostics_surface(tmp_path):
    files = {
        "caller.py": "import dep\nprint(dep.VALUE)\n",
        "entry.py": "import caller\n",
        "other.py": "print(old_problem)\n",
    }
    base, head = trees(tmp_path, {"dep.py": "VALUE = 42\n", **files}, files)
    old = diagnostic("other.py", 1)
    runner = Runner([old], [old, diagnostic()])
    result, ai = review(base, head, runner)
    assert runner.calls == [("head", set(files)), ("base", {*files, "dep.py"})]
    assert result.status == "completed"
    assert any(f.file == "caller.py" and f.baseline_status == "introduced" for f in result.findings)
    assert any(
        f.file == "other.py" and "base tree" in f.suppressed_reason for f in result.suppressed
    )
    assert any(b.file == "caller.py" for b in ai.requests[0].context)
    assert "VALUE = 42" in ai.requests[0].diff
    assert result.summary.stats.files_reviewed == 1
    assert {r.tool for r in result.analysis_runs} == {"ruff", "base:ruff"}


@pytest.mark.parametrize("status", ["failed", "timeout", "unavailable", "skipped"])
def test_incomplete_base_never_suppresses_a_head_diagnostic(tmp_path, status):
    base, head = trees(tmp_path, {"caller.py": "x\nproblem\n"}, {"caller.py": "x\nproblem\n"})
    result, _ = review(base, head, Runner([diagnostic()], [diagnostic()], base_status=status))
    assert result.status == "partial"
    assert result.findings[0].baseline_status == "unknown"
    assert any("comparison unavailable" in message for message in result.errors)


def test_failed_head_stays_partial_even_when_base_succeeded(tmp_path):
    base, head = trees(tmp_path, {"a.py": "x = 1\n"}, {"a.py": "x = 1\n"})
    result, _ = review(base, head, Runner(head_status="timeout"))
    assert result.status == "partial"
    assert "No problems found" not in result.summary.headline


@pytest.mark.parametrize("renamed", [False, True])
def test_line_shifts_and_renames_preserve_existing_diagnostics_without_hiding_new_sites(renamed):
    path = "new.py" if renamed else "old.py"
    change = (
        parse_unified_diff(
            "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
        )
        if renamed
        else ChangeSet()
    )
    before = [diagnostic("old.py", 2)]
    after = [diagnostic(path, 4), diagnostic(path, 6)]
    compare_diagnostics(
        before,
        after,
        {"old.py": "def f():\n    problem()\n"},
        {path: "# inserted\n\ndef f():\n    problem()\n\ndef g(): problem()\n"},
        change,
        {"ruff"},
    )
    assert [f.baseline_status for f in after] == ["pre-existing", "introduced"]


def test_changed_diagnostic_rule_or_message_is_new():
    before = [diagnostic()]
    after = [diagnostic(title="New error"), diagnostic(rule="F999")]
    sources = {"caller.py": "# header\nproblem()\n"}
    compare_diagnostics(before, after, sources, sources, ChangeSet(), {"ruff"})
    assert all(f.baseline_status == "introduced" for f in after)


def test_duplicate_diagnostic_multiplicity_is_preserved():
    before = [diagnostic()]
    after = [diagnostic(), diagnostic()]
    sources = {"caller.py": "# header\nproblem()\n"}
    compare_diagnostics(before, after, sources, sources, ChangeSet(), {"ruff"})
    assert [f.baseline_status for f in after] == ["pre-existing", "introduced"]


def test_unknown_and_new_findings_are_not_hidden_when_merged_with_existing():
    old, new = diagnostic(), diagnostic()
    old.baseline_status, new.baseline_status = "pre-existing", "introduced"
    old.in_changed_lines = False
    merged = merge([old, new])
    assert merged.baseline_status == "introduced" and merged.in_changed_lines
    new.baseline_status = "unknown"
    assert merge([old, new]).baseline_status == "unknown"
    new.baseline_status = None
    new.origins = ["ai:scripted"]
    assert merge([old, new]).baseline_status == "pre-existing"


@pytest.mark.parametrize(
    "files",
    [
        {"caller.py": "import dep\n", "dep.py": "VALUE = 42\n"},
        {"caller.js": "import './dep.js';\n", "dep.js": "export const value = 42;\n"},
        {"caller.ts": "import {value} from './dep';\n", "dep.ts": "export const value = 42;\n"},
        {
            "pkg/__init__.py": "",
            "pkg/caller.py": "from .dep import VALUE\n",
            "pkg/dep.py": "VALUE = 42\n",
        },
    ],
)
def test_removed_local_module_is_detected_in_unchanged_python_and_js_ts_importers(files):
    registry = default_registry()
    after = {k: v for k, v in files.items() if "/dep." not in k and not k.startswith("dep.")}
    change = ChangeSet(
        files=[
            FileChange(path=p, change_type=ChangeType.DELETED) for p in files.keys() - after.keys()
        ]
    )
    found = broken_imports(registry.analyze(files), registry.analyze(after), change)
    assert len(found) == 1
    assert "caller" in found[0].file and found[0].baseline_status == "introduced"


def test_external_imports_and_updated_imports_are_not_false_deletion_findings():
    registry = default_registry()
    before = {"caller.py": "import external\nimport dep\n", "dep.py": "VALUE = 1\n"}
    after = {"caller.py": "import external\nimport replacement\n", "replacement.py": "VALUE = 1\n"}
    assert not broken_imports(registry.analyze(before), registry.analyze(after), ChangeSet())


def test_limits_and_ignored_files_are_explicit_and_not_analyzed(tmp_path):
    files = {"a.py": "x=1\n", "b.py": "x=1\n", "ignored.py": "secret=1\n"}
    base, head = trees(tmp_path, files, files)
    runner = Runner()
    result, _ = review(base, head, runner, config=RepoConfig(ignore=["ignored.py"]), max_files=1)
    assert result.status == "partial"
    assert any("inventory" in message for message in result.errors)
    assert all("ignored.py" not in targets for _, targets in runner.calls)


def test_parse_failures_are_not_a_complete_deletion_review(tmp_path):
    base, head = trees(tmp_path, {"a.py": "def broken(\n"}, {"a.py": "x = 1\n"})
    result, _ = review(base, head, Runner())
    assert result.status == "partial"
    assert any("dependency parsing" in message for message in result.errors)


def test_pure_deletion_with_no_surviving_sources_is_reviewed(tmp_path):
    base, head = trees(tmp_path, {"dep.py": "VALUE = 42\n"}, {})
    result, ai = review(base, head, Runner())
    assert result.status == "completed" and ai.requests
    assert result.summary.stats.files_reviewed == 1


def test_base_inventory_unreadable_never_establishes_newness(tmp_path):
    base, head = trees(
        tmp_path, {"caller.py": "# header\nproblem()\n"}, {"caller.py": "# header\nproblem()\n"}
    )
    (base / "escape.py").symlink_to(tmp_path / "outside.py")
    (tmp_path / "outside.py").write_text("SECRET = 1\n")
    result, _ = review(base, head, Runner([], [diagnostic()]))
    assert result.status == "partial" and result.findings[0].baseline_status == "unknown"


def test_missing_analyzer_records_are_partial_even_for_pure_deletion(tmp_path):
    base, head = trees(tmp_path, {"dep.py": "VALUE = 42\n"}, {})

    class EmptyRunner:
        def run(self, root, files):
            return [], []

    result, _ = review(base, head, EmptyRunner())
    assert result.status == "partial"
    assert any("no base analyzer" in message for message in result.errors)


def test_omitted_source_is_not_misidentified_as_deleted_module():
    registry = default_registry()
    files = {"dep.py": "VALUE = 42\n", "caller.py": "import dep\n"}
    assert not broken_imports(
        registry.analyze(files), registry.analyze({"caller.py": files["caller.py"]}), ChangeSet()
    )


@pytest.mark.parametrize("new_file", [False, True])
def test_new_import_of_deleted_local_module_is_not_missed(new_file):
    registry = default_registry()
    before = {"dep.py": "VALUE = 42\n"}
    if not new_file:
        before["caller.py"] = "# no import yet\n"
    after = {"caller.py": "import dep\nprint(dep.VALUE)\n"}
    change = parse_unified_diff(DELETE)
    findings = broken_imports(registry.analyze(before), registry.analyze(after), change)
    assert len(findings) == 1 and findings[0].file == "caller.py"


def test_impact_context_budget_still_bounds_request(tmp_path):
    source = ("# " + "x" * 250 + "\n") * 300
    base, head = trees(
        tmp_path,
        {"dep.py": "VALUE=42\n", "caller.py": source},
        {"caller.py": source},
    )
    config = RepoConfig()
    config.review.max_context_chars = 2000
    result, ai = review(base, head, Runner([], [diagnostic()]), config=config)
    assert sum(len(b.code) for b in ai.requests[0].context) <= 2000
    assert result.summary.stats.files_reviewed == 1
    assert result.status == "partial"
    assert any("context budget" in error for error in result.errors)


def test_impact_context_and_deleted_diff_are_redacted(tmp_path):
    secret = "sk_live_" + "a" * 24
    source = f"# {secret}\nprint(problem)\n"
    base, head = trees(
        tmp_path, {"dep.py": f"API_KEY = '{secret}'\n", "caller.py": source}, {"caller.py": source}
    )
    change = parse_unified_diff(DELETE.replace("VALUE = 42", f"API_KEY = '{secret}'"))
    _, ai = review(base, head, Runner([], [diagnostic()]), change=change)
    assert secret not in ai.requests[0].model_dump_json()
