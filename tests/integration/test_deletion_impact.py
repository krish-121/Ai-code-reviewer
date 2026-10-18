"""S16: real analyzers and immutable local/GitHub baseline acquisition."""

import json

import httpx
import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.diff.git import range_changeset
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.static.js_tools import TscAnalyzer
from sentinel.analysis.static.python_tools import MypyAnalyzer, RuffAnalyzer
from sentinel.analysis.static.runner import StaticAnalysisRunner
from sentinel.bootstrap import default_verifier
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import ChangeSet
from sentinel.core.review.orchestrator import ReviewOrchestrator
from sentinel.integrations.github.client import GitHubClient, StaticToken
from sentinel.services.baselines import github_baseline
from sentinel.services.workspaces import LocalRequest, prepare_baseline, prepare_local
from tests.fakes import ScriptedProvider
from tests.integration.test_pipeline import git
from tests.unit.test_deletion_impact import DELETE, trees


def engine(tools, ai=None):
    return ReviewOrchestrator(
        extractor=default_registry(),
        static_runner=StaticAnalysisRunner(tools),
        verifier=default_verifier(),
        ai=ai,
        config=RepoConfig(),
    )


def test_removed_python_export_breaks_unchanged_caller_and_transitive_entrypoint(tmp_path):
    dependent = {
        "caller.py": "from dep import value\ndef call() -> int:\n    return value()\n",
        "entry.py": "from caller import call\nprint(call())\n",
    }
    base, head = trees(
        tmp_path,
        {"dep.py": "def value() -> int:\n    return 42\n", **dependent},
        {"dep.py": "# export removed\n", **dependent},
    )
    change = parse_unified_diff(
        DELETE.replace("deleted file mode 100644\n", "").replace("+++ /dev/null", "+++ b/dep.py")
    )
    result = engine(
        [RuffAnalyzer(trust_workspace=False), MypyAnalyzer(trust_workspace=False)]
    ).review(change, head, baseline=base)
    assert result.status == "completed", result.errors
    assert any(
        f.file == "caller.py"
        and "attr-defined" in str(f.origins)
        and f.baseline_status == "introduced"
        for f in result.findings
    )
    assert {r.tool for r in result.analysis_runs} == {"ruff", "mypy", "base:ruff", "base:mypy"}


def test_removing_assignment_exposes_new_error_on_unchanged_line(tmp_path):
    base, head = trees(
        tmp_path,
        {"caller.py": "value = 42\n" + "\n" * 8 + "print(value)\n"},
        {"caller.py": "\n" * 8 + "print(value)\n"},
    )
    change = parse_unified_diff(
        "diff --git a/caller.py b/caller.py\n--- a/caller.py\n+++ b/caller.py\n@@ -1 +0,0 @@\n-value = 42\n"
    )
    result = engine([RuffAnalyzer(trust_workspace=False)]).review(change, head, baseline=base)
    assert result.status == "completed"
    assert any(f.line_start == 9 and f.baseline_status == "introduced" for f in result.findings)


def test_typescript_deleted_module_reports_unchanged_import_and_caller(tmp_path):
    config = json.dumps({"compilerOptions": {"strict": True, "noEmit": True}, "include": ["*.ts"]})
    shared = {
        "tsconfig.json": config,
        "caller.ts": "import {value} from './dep';\nexport const call = () => value();\n",
    }
    base, head = trees(tmp_path, {"dep.ts": "export const value = () => 42;\n", **shared}, shared)
    change = parse_unified_diff(
        DELETE.replace("dep.py", "dep.ts").replace("VALUE = 42", "export const value = () => 42;")
    )
    result = engine([TscAnalyzer(trust_workspace=False)]).review(change, head, baseline=base)
    assert result.status == "completed", result.errors
    assert any(f.file == "caller.ts" and f.baseline_status == "introduced" for f in result.findings)
    assert any("2307" in str(f.origins) for f in result.findings)


def initialize(root):
    root.mkdir()
    (root / "dep.py").write_text("VALUE = 42\n")
    (root / "caller.py").write_text("import dep\nprint(dep.VALUE)\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD").strip()


@pytest.mark.parametrize("mode", ["staged", "range", "worktree"])
def test_local_review_exports_the_correct_baseline(tmp_path, mode):
    root = tmp_path / "repo"
    commit = initialize(root)
    (root / "dep.py").unlink()
    git(root, "add", "-A")
    if mode == "range":
        git(root, "commit", "-qm", "delete")
    with prepare_local(LocalRequest(path=str(root), mode=mode)) as workspace:
        assert workspace.baseline is not None and workspace.baseline_error is None
        assert (workspace.baseline / "dep.py").read_text() == "VALUE = 42\n"
        assert workspace.changeset.baseline_ref == commit
        assert not (workspace.workspace / "dep.py").exists()
        (root / "caller.py").write_text("# edited after snapshot\n")
        assert "import dep" in (workspace.workspace / "caller.py").read_text()
        baseline = workspace.baseline
    assert not baseline.exists()


def test_range_uses_merge_base_not_base_branch_tip(tmp_path):
    root = tmp_path / "repo"
    ancestor = initialize(root)
    git(root, "checkout", "-qb", "feature")
    (root / "dep.py").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feature deletion")
    git(root, "checkout", "-q", "main")
    (root / "dep.py").write_text("VALUE = 99\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base branch advanced")
    change = range_changeset(root, "main", "feature")
    assert change.base_ref == ancestor
    with prepare_local(
        LocalRequest(path=str(root), mode="range", base="main", head="feature")
    ) as workspace:
        assert (workspace.baseline / "dep.py").read_text() == "VALUE = 42\n"


def test_missing_local_base_yields_explicit_incomplete_review(tmp_path):
    change = parse_unified_diff(DELETE)
    change.base_ref = "does-not-exist"
    with prepare_baseline(tmp_path, change) as (baseline, error):
        assert baseline is None and "unavailable" in error
        result = engine([RuffAnalyzer(trust_workspace=False)], ScriptedProvider()).review(
            change, tmp_path, baseline=baseline, baseline_error=error
        )
    assert result.status == "partial" and "limitations" in result.summary.headline


def test_github_pins_the_merge_base_and_downloads_it(tmp_path, monkeypatch):
    calls = []
    ancestor = "a" * 40

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"merge_base_commit": {"sha": ancestor}})

    client = GitHubClient(StaticToken("test"), transport=httpx.MockTransport(handler))

    def download(repo, ref, destination):
        assert ref == ancestor
        (destination / "dep.py").write_text("VALUE = 42\n")

    monkeypatch.setattr(client, "download_tree", download)
    change = parse_unified_diff(DELETE)
    change.base_ref, change.head_ref = "b" * 40, "c" * 40
    with github_baseline(client, "owner/repo", change) as (baseline, error):
        assert error is None and (baseline / "dep.py").exists()
        assert change.baseline_ref == ancestor
        assert change.base_ref == "b" * 40  # still the PR revision guard
    assert not baseline.exists()
    assert calls == [f"/repos/owner/repo/compare/{'b' * 40}...{'c' * 40}"]


@pytest.mark.parametrize("response", [{}, {"merge_base_commit": {"sha": "bad"}}])
def test_invalid_github_baseline_is_partial_not_a_silent_empty_tree(response):
    client = GitHubClient(
        StaticToken("test"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    )
    change = parse_unified_diff(DELETE)
    change.base_ref, change.head_ref = "b" * 40, "c" * 40
    with github_baseline(client, "owner/repo", change) as (baseline, error):
        assert baseline is None and "unavailable" in error


def test_non_deletion_needs_no_github_baseline():
    with github_baseline(None, "owner/repo", ChangeSet()) as result:
        assert result == (None, None)
