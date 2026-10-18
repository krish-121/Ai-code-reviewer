"""Coordinated edits, new regression tests, and safe multi-file application."""

import pytest

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import FileEdit
from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
from sentinel.core.fixes.context import fix_context
from sentinel.core.fixes.engine import ApplyError, apply_fix
from sentinel.core.fixes.patch import PatchError, apply_edits
from sentinel.infrastructure.database.models import FixAttempt
from sentinel.services.fixes import FixService
from tests.fakes import ScriptedProvider
from tests.unit.test_fix_engine import FakeSandbox, engine, ok

BEFORE = "    return cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n"
AFTER = '    return cur.execute("SELECT * FROM users WHERE name = ?", (name,))\n'
TEST = """from query import query
from helper import label

def test_regression():
    class Cursor:
        def execute(self, sql, params=()):
            assert '?' in sql and params == ('Alice',)
    query(Cursor(), 'Alice')
    assert label() == 'safe'
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "query.py").write_text("from helper import label\ndef query(cur, name):\n" + BEFORE)
    (tmp_path / "helper.py").write_text("def label():\n    return 'unsafe'\n")
    return tmp_path


def issue():
    return Finding(
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.9,
        title="SQL injection",
        explanation="interpolated SQL",
        file="query.py",
        line_start=3,
        line_end=3,
        source=FindingSource.STATIC_ANALYZER,
        origins=["sentinel:sql-injection"],
        tags=["sql-injection"],
    )


def proposal():
    return {
        "summary": "Parameterize and test the coordinated change",
        "edits": [
            {"file": "query.py", "search": BEFORE, "replace": AFTER},
            {"file": "helper.py", "search": "'unsafe'", "replace": "'safe'"},
            {
                "file": "test_query_regression.py",
                "search": "",
                "replace": TEST,
                "operation": "create",
            },
        ],
    }


def outcome(root):
    ai = ScriptedProvider(fixes=[proposal()])
    sandbox = FakeSandbox(ok(5, "no tests ran"), ok(), ok(1, "1 failed"), ok())
    result = engine(ai, sandbox, root).generate(issue(), root)
    assert result.status == "validated", result.checks
    return result, ai


def test_multi_file_generation_and_new_regression_do_not_touch_the_original(project):
    result, ai = outcome(project)
    request = ai.fix_requests[0]
    assert set(request.files) == {"query.py", "helper.py"}
    assert request.allowed_new_files == ["test_query_regression.py"]
    assert "'unsafe'" in (project / "helper.py").read_text()
    assert not (project / "test_query_regression.py").exists()
    assert result.original_hashes["test_query_regression.py"] is None
    assert "new file mode" in result.patch and "--- /dev/null" in result.patch
    assert any(c.name == "regression-tests" and c.status == "passed" for c in result.checks)
    assert apply_fix(project, result) == ["helper.py", "query.py", "test_query_regression.py"]
    assert "'safe'" in (project / "helper.py").read_text()
    assert (project / "test_query_regression.py").read_text() == TEST


def test_stale_secondary_file_prevents_all_writes(project):
    result, _ = outcome(project)
    original = (project / "query.py").read_text()
    (project / "helper.py").write_text("# user edit\n")
    with pytest.raises(ApplyError, match="changed since"):
        apply_fix(project, result)
    assert (project / "query.py").read_text() == original
    assert not (project / "test_query_regression.py").exists()


def test_existing_new_path_is_never_overwritten(project):
    result, _ = outcome(project)
    original = (project / "query.py").read_text()
    (project / "test_query_regression.py").write_text("# user's file\n")
    with pytest.raises(ApplyError, match="already exists"):
        apply_fix(project, result)
    assert (project / "query.py").read_text() == original
    assert (project / "test_query_regression.py").read_text() == "# user's file\n"


@pytest.mark.parametrize("parent_link", [False, True])
def test_created_test_cannot_follow_a_symlink_outside_the_repository(project, parent_link):
    result, _ = outcome(project)
    outside = project.parent / f"{project.name}-outside"
    outside.mkdir()
    marker = outside / "keep.py"
    marker.write_text("# untouched\n")
    path = "tests/new.py" if parent_link else "test_query_regression.py"
    if parent_link:
        (project / "tests").symlink_to(outside, target_is_directory=True)
    else:
        (project / path).symlink_to(marker)
    result.edits[-1].file = path
    del result.original_hashes["test_query_regression.py"]
    result.original_hashes[path] = None
    with pytest.raises(ApplyError):
        apply_fix(project, result)
    assert marker.read_text() == "# untouched\n"
    assert not (outside / "new.py").exists()
    assert BEFORE in (project / "query.py").read_text()


def test_write_failure_rolls_back_modified_files_and_removes_created_files(project, monkeypatch):
    from sentinel.core.fixes import apply

    result, _ = outcome(project)
    before = {p.name: p.read_text() for p in project.iterdir()}
    replace = apply._replace_text
    calls = 0

    def fail_once(stream, content):
        nonlocal calls
        calls += 1
        replace(stream, content)
        if calls == 3:
            raise OSError("injected partial write")

    monkeypatch.setattr(apply, "_replace_text", fail_once)
    with pytest.raises(ApplyError, match="injected"):
        apply_fix(project, result)
    assert {p.name: p.read_text() for p in project.iterdir()} == before


def test_new_path_race_preserves_other_writers_file_and_restores_our_edits(project, monkeypatch):
    from sentinel.core.fixes import apply

    result, _ = outcome(project)
    commit = apply._commit

    def race(*args):
        (project / "test_query_regression.py").write_text("# concurrent writer\n")
        return commit(*args)

    monkeypatch.setattr(apply, "_commit", race)
    with pytest.raises(ApplyError):
        apply_fix(project, result)
    assert BEFORE in (project / "query.py").read_text()
    assert "'unsafe'" in (project / "helper.py").read_text()
    assert (project / "test_query_regression.py").read_text() == "# concurrent writer\n"


def test_context_respects_limits_and_rejects_explicit_sensitive_files(project):
    config = RepoConfig()
    config.fix.max_files = 1
    assert list(fix_context(project, issue(), config).files) == ["query.py"]
    config.ignore = ["helper.py", "test_*.py"]
    context = fix_context(project, issue(), config)
    assert "helper.py" not in context.files and context.new_files == []
    config.fix.context_files = [".env"]
    from sentinel.core.paths import RepositoryPathError

    with pytest.raises(RepositoryPathError):
        fix_context(project, issue(), config)


def test_new_test_manifest_survives_service_serialization(project):
    result, _ = outcome(project)
    stored = FixAttempt(
        status=result.status,
        original_hashes=result.original_hashes,
        edits=[edit.model_dump() for edit in result.edits],
        checks=[],
        attempts=1,
    )
    loaded = FixService.outcome_of(stored)
    assert loaded.original_hashes["test_query_regression.py"] is None
    assert loaded.edits[-1].operation == "create"


@pytest.mark.parametrize(
    "edit",
    [
        FileEdit(file="new.py", search="", replace="x=1", operation="create"),
        FileEdit(file="../outside.py", search="", replace="x=1", operation="create"),
    ],
)
def test_create_outside_advertised_slots_is_rejected(edit):
    with pytest.raises((PatchError, ValueError)):
        apply_edits({}, [edit], ["test_safe.py"])


@pytest.mark.parametrize(
    "baseline", [ok(), ok(2, "1 error"), ok(1, "1 error"), ok(124, "timed out")]
)
def test_generated_test_must_fail_for_the_original_code(project, baseline):
    ai = ScriptedProvider(fixes=[proposal()])
    sandbox = FakeSandbox(ok(5), ok(), baseline)
    built = engine(ai, sandbox, project)
    built.max_attempts = 1
    result = built.generate(issue(), project)
    assert result.status == "failed"
    assert any(c.name == "regression-tests" and c.status == "failed" for c in result.checks)
