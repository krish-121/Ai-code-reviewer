"""Regressions for the nine high-priority engineering-audit blockers (S01–S09)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sentinel.analysis.diff.filtering import filter_changeset
from sentinel.analysis.diff.git import GitError, path_changeset
from sentinel.analysis.diff.parser import whole_file_change
from sentinel.analysis.diff.secrets import redact_text
from sentinel.analysis.static.base import ToolResult, run_record
from sentinel.analysis.static.probes.sql import SqlInjectionProbe
from sentinel.bootstrap import build_fix_engine
from sentinel.core.configuration.config import RepoConfig, Settings
from sentinel.core.domain.ai import FileEdit
from sentinel.core.domain.models import AnalysisRun, ChangeSet, Language
from sentinel.core.fixes.engine import ApplyError, FixOutcome, _verdict, apply_fix
from sentinel.core.fixes.outcome import FixCheck
from sentinel.core.fixes.patch import PatchError, apply_edits, sha256
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.core.fixes.validation import check_analysis, check_resolved, check_tests
from sentinel.core.paths import RepositoryPathError, read_repository_text, relative_file
from sentinel.core.review.workspace import collect_sources, snapshot_sources
from sentinel.sandbox.analysis import AnalysisReport, SandboxStaticRunner
from sentinel.services.workspaces import LocalRequest, authorize_root, prepare_local
from tests.fakes import ScriptedProvider
from tests.unit.test_fix_engine import FakeSandbox, engine, ok, sqli_finding
from tests.unit.test_verification import ctx, finding


@pytest.mark.parametrize(
    "path", ["/tmp/x.py", "../x.py", "a/../x.py", "C:/x.py", "a\\x.py", "a//x.py"]
)
def test_s01_noncanonical_paths_never_reach_provider(tmp_path: Path, path: str) -> None:
    ai = ScriptedProvider()
    result = engine(ai, None, tmp_path).generate(
        sqli_finding().model_copy(update={"file": path}), tmp_path
    )
    assert result.status == "error" and not ai.fix_requests
    with pytest.raises(RepositoryPathError):
        relative_file(path)


@pytest.mark.parametrize("directory", [False, True])
def test_s01_symlinks_cannot_read_or_apply_outside_repo(tmp_path: Path, directory: bool) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "x.py"
    target.write_text("secret = 1\n")
    rel = "link/x.py" if directory else "x.py"
    (root / "link" if directory else root / rel).symlink_to(
        outside if directory else target, target_is_directory=directory
    )
    with pytest.raises(OSError, match=r"symbolic links|Not a directory"):
        read_repository_text(root, rel)
    outcome = FixOutcome(
        status="validated",
        original_hashes={rel: sha256(target.read_text())},
        edits=[FileEdit(file=rel, search="1", replace="2")],
    )
    with pytest.raises(ApplyError):
        apply_fix(root, outcome)
    assert target.read_text() == "secret = 1\n"


def test_s01_scratch_has_no_links_to_original_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("original")
    (root / "linked.py").symlink_to(outside)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("original")
    (root / ".env").write_text("PASSWORD=never_copy_credentials")
    copied = scratch_copy(root)
    try:
        assert not list(copied.iterdir())
    finally:
        shutil.rmtree(copied)


def test_s02_no_host_execution_when_docker_is_absent(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "mypy.ini").write_text("[mypy]\nplugins = evil.py\n")
    marker = tmp_path / "executed"
    (tmp_path / "evil.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    ai = ScriptedProvider(
        fixes=[{"summary": "change", "edits": [{"file": "a.py", "search": "1", "replace": "2"}]}]
    )
    fix = build_fix_engine(Settings(), RepoConfig(), workspace=tmp_path, ai=ai, sandbox=None)
    result = fix.generate(sqli_finding().model_copy(update={"file": "a.py"}), tmp_path)
    assert result.status == "unverified"
    assert not marker.exists() and (tmp_path / "a.py").read_text() == "x = 1\n"


def test_s02_container_entry_point_cannot_be_shadowed_by_workspace(tmp_path: Path) -> None:
    report = AnalysisReport(findings=[], runs=[AnalysisRun(tool="sentinel", status="ok")])
    sandbox = FakeSandbox(ok(out=report.model_dump_json()))
    findings, runs = SandboxStaticRunner(sandbox, RepoConfig()).run(tmp_path, ["a.py"])
    assert not findings and runs[0].status == "ok"
    assert sandbox.commands[0][1][:4] == ["python", "-I", "-m", "sentinel.sandbox.analyze"]
    sandbox.isolation = "process"
    result = check_tests(sandbox, ["python", "evil.py"], 5, tmp_path, tmp_path)
    assert result.status == "skipped" and len(sandbox.commands) == 1


@pytest.mark.parametrize("output", ["not json", '{"findings": [], "runs":', "{}"])
def test_s02_invalid_container_reports_fail_closed(tmp_path: Path, output: str) -> None:
    sandbox = FakeSandbox(ok(out=output))
    _, runs = SandboxStaticRunner(sandbox, RepoConfig()).run(tmp_path, ["a.py"])
    assert runs[0].status == "failed"


def test_s03_multiline_key_redaction_preserves_diff_lines() -> None:
    body = "SYNTHETICKEYBODY1234567890"
    source = f'KEY = """-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"""\nx = 1\n'
    out = filter_changeset(ChangeSet(files=[whole_file_change("cfg.py", source)]))
    lines = [line for h in out.changeset.files[0].hunks for line in h.lines]
    assert body not in "\n".join(line.content for line in lines)
    assert len(lines) == len(source.splitlines())
    assert "x = 1" in lines[-1].content


@pytest.mark.parametrize("secret", ["Abcd-test-X9w7Z3k2", "aB3!cD4?eF5#gH6", "lowentropyvalue"])
def test_s03_redaction_is_not_weakened_by_placeholder_heuristics(secret: str) -> None:
    text, _ = redact_text(f'password = "{secret}"')
    assert secret not in text


def test_s03_sensitive_fix_request_rejected_before_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PASSWORD=must-never-reach-ai\n")
    ai = ScriptedProvider()
    outcome = engine(ai, None, tmp_path).generate(
        sqli_finding().model_copy(update={"file": ".env"}), tmp_path
    )
    assert outcome.status == "error" and not ai.fix_requests


def test_s03_raw_fix_request_and_prompt_have_no_credentials() -> None:
    from sentinel.ai.prompts import build_fix_prompt
    from sentinel.core.fixes.engine import _fix_request

    secret = "AbCd-test-X9w7Z3k2"
    content = f'password = "{secret}"\n'
    issue = sqli_finding().model_copy(update={"title": content, "explanation": content})
    request = _fix_request(issue, {"app/db.py": content}, content)
    assert secret not in request.model_dump_json()
    assert secret not in build_fix_prompt(request).user


def test_s04_context_and_snapshot_honor_ignore_and_language(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "ignored.py").write_text("never_send = 2\n")
    (tmp_path / "other.ts").write_text("const neverSend = 3;\n")
    snapshot = collect_sources(
        tmp_path,
        {".py", ".ts"},
        ["ignored.py", "other.ts", "keep.py"],
        ignore=["ignored.py"],
        languages=[Language.PYTHON],
    )
    assert set(snapshot.sources) == {"keep.py"}
    cs = ChangeSet(files=[whole_file_change("ignored.py", "")])
    assert snapshot_sources(cs, snapshot.sources, None, []) == {}


def test_s05_effective_git_root_must_be_authorized(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    with pytest.raises(GitError, match="effective repository root"):
        authorize_root(allowed, [allowed])
    request = LocalRequest(path=str(allowed), mode="path", allowed_roots=[str(allowed)])
    with pytest.raises(GitError, match="effective repository root"), prepare_local(request):
        pytest.fail("must reject before review starts")
    assert authorize_root(allowed, [tmp_path]) == tmp_path


def test_s05_review_never_reads_external_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "outside.py"
    secret.write_text("outside_value = 'not authorized'\n")
    (root / "link.py").symlink_to(secret)
    assert not collect_sources(root, {".py"}, ["link.py"]).sources
    assert not path_changeset(root).files


@pytest.mark.parametrize(
    ("tool", "code", "stdout"),
    [
        ("ruff", 2, "[]"),
        ("ruff", 0, "invalid"),
        ("bandit", 2, '{"results":[]}'),
        ("bandit", 0, '{"results":[],"errors":[{"reason":"unreadable"}]}'),
        ("eslint", 1, '[{"messages":[{"fatal":true}]}]'),
        ("mypy", 2, ""),
        ("mypy", 0, "invalid output"),
        ("tsc", 2, "error TS18003: No inputs found"),
    ],
)
def test_s06_failed_or_malformed_tool_output_is_not_success(
    tool: str, code: int, stdout: str
) -> None:
    record = run_record(tool, ToolResult(code, stdout, "", 1), 0)
    assert record.status == "failed"


@pytest.mark.parametrize(
    ("tool", "code", "stdout"),
    [
        ("ruff", 0, "[]"),
        ("bandit", 1, '{"results":[],"errors":[]}'),
        ("mypy", 1, "a.py:2: error: bad type  [arg-type]"),
        ("tsc", 2, "a.ts(1,2): error TS2345: bad type"),
    ],
)
def test_s06_valid_tool_diagnostics_still_succeed(tool: str, code: int, stdout: str) -> None:
    assert run_record(tool, ToolResult(code, stdout, "", 1), 0).status == "ok"


@pytest.mark.parametrize("status", ["failed", "timeout", "unavailable", "skipped"])
def test_s07_incomplete_analysis_cannot_validate(status: str) -> None:
    before = [AnalysisRun(tool="ruff", status="ok")]
    analysis = check_analysis(before, [AnalysisRun(tool="ruff", status=status)])
    checks = [
        analysis,
        *[
            FixCheck(name=n, status="passed", detail="")
            for n in ("tests", "finding-resolved", "no-new-issues")
        ],
    ]
    assert _verdict(checks) == "unverified"
    assert check_analysis([], []).status == "skipped"


def test_s07_fixing_a_different_occurrence_does_not_resolve_target() -> None:
    target = sqli_finding().model_copy(update={"rule_id": "sentinel/sql-injection"})
    other = target.model_copy(update={"line_start": 70, "line_end": 70})
    assert check_resolved(target, [target, other], [target], 0).status == "failed"
    assert check_resolved(target, [other], [], 0).status == "skipped"
    assert _verdict([FixCheck(name="tests", status="passed", detail="")]) == "unverified"


def test_s07_noop_edits_rejected_and_whitespace_preserved() -> None:
    edit = FileEdit(file="a.py", search="    x = 1\n", replace="    x = 2\n")
    assert edit.search.startswith("    ") and edit.replace.endswith("\n")
    with pytest.raises(PatchError, match="no changes"):
        apply_edits({"a.py": "x"}, [FileEdit(file="a.py", search="x", replace="x")])


@pytest.mark.parametrize("query", ["query", "builder(query)", "unknown.value"])
def test_s08_unknown_sql_is_not_decisively_safe(query: str) -> None:
    context = ctx(app__unknown_py=f"def run(cur, query):\n    cur.execute({query})\n")
    result = SqlInjectionProbe().check(
        finding(title="SQL injection", file="app/unknown.py", line_start=2, line_end=2), context
    )
    assert result is not None and result.outcome == "neutral" and not result.decisive


def test_s09_existing_demo_directory_is_never_deleted(tmp_path: Path) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "demo" / "build_demo_repo.py"
    spec = importlib.util.spec_from_file_location("sentinel_demo_builder", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marker = tmp_path / "precious.txt"
    marker.write_text("keep me")
    with pytest.raises(FileExistsError):
        module.build(tmp_path)
    assert marker.read_text() == "keep me"
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(FileExistsError):
        module.build(link)
    assert marker.read_text() == "keep me"
