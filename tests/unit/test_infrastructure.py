from __future__ import annotations

import ast
import json
import logging
import subprocess
from pathlib import Path

import pytest

from sentinel.analysis.diff.git import GitError, export_tree, list_files, rev_parse
from sentinel.core.domain.models import (
    ChangeSet,
    ReviewResult,
    ReviewStatus,
    StageName,
    StageRecord,
    StageStatus,
)
from sentinel.core.review.workspace import collect_sources
from sentinel.infrastructure.observability.logging import (
    JsonFormatter,
    KeyValueFormatter,
    configure_logging,
    review_id_var,
)
from sentinel.infrastructure.observability.metrics import Metrics
from sentinel.infrastructure.storage.cache import DiskCache, MemoryCache, content_key
from sentinel.services.workspaces import LocalRequest, prepare_local

SRC = Path(__file__).resolve().parents[2] / "src" / "sentinel"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "HOME": str(repo),
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
            "PATH": "/usr/bin:/bin",
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("def a():\n    return 1\n")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("x")
    (root / ".gitignore").write_text("node_modules/\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "one")
    (root / "pkg" / "a.py").write_text("def a():\n    return 2\n")
    git(root, "commit", "-qam", "two")
    return root


# ----------------------------------------------------------------- architecture


FORBIDDEN_IN_CORE = (
    "fastapi",
    "sqlalchemy",
    "httpx",
    "starlette",
    "typer",
    "rich",
    "sentinel.apps",
    "sentinel.infrastructure.database",
    "sentinel.infrastructure.queue",
    "sentinel.integrations",
    "sentinel.ai.providers",
    "sentinel.sandbox",
    "sentinel.services",
    "sentinel.bootstrap",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_core_does_not_depend_on_delivery_or_vendors() -> None:
    violations = []
    for path in (SRC / "core").rglob("*.py"):
        for mod in _imports(path):
            if any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN_IN_CORE):
                violations.append(f"{path.relative_to(SRC)} imports {mod}")
    assert violations == []


def test_domain_is_pure() -> None:
    allowed = (
        "__future__",
        "pydantic",
        "sentinel.core.domain",
        "collections",
        "dataclasses",
        "datetime",
        "enum",
        "pathlib",
        "typing",
        "uuid",
    )
    for path in (SRC / "core" / "domain").rglob("*.py"):
        for mod in _imports(path):
            assert mod.startswith(allowed), f"{path.name} imports {mod}"


def test_analysis_never_imports_vendor_ai_or_web() -> None:
    for path in (SRC / "analysis").rglob("*.py"):
        for mod in _imports(path):
            assert not mod.startswith(
                ("fastapi", "sqlalchemy", "httpx", "sentinel.ai.providers", "sentinel.apps")
            ), f"{path.name} imports {mod}"


# ----------------------------------------------------------------- workspaces


def test_prepare_local_modes(repo: Path) -> None:
    (repo / "pkg" / "a.py").write_text("def a():\n    return 3\n")
    git(repo, "add", "pkg/a.py")
    with prepare_local(LocalRequest(path=str(repo), mode="staged")) as ws:
        assert ws.workspace == repo  # staged == worktree for the changed file
        assert [f.path for f in ws.changeset.files] == ["pkg/a.py"]
    # an unstaged edit on top of the staged one -> the index is exported
    (repo / "pkg" / "a.py").write_text("def a():\n    return 4\n")
    with prepare_local(LocalRequest(path=str(repo), mode="staged")) as ws:
        assert ws.workspace != repo
        assert "return 3" in (ws.workspace / "pkg" / "a.py").read_text()
        exported = ws.workspace
    assert not exported.exists()  # cleaned up
    with prepare_local(LocalRequest(path=str(repo), mode="worktree")) as ws:
        assert "return 4" in "".join(
            ln.content for h in ws.changeset.files[0].hunks for ln in h.lines
        )
    # a range whose head is not the checkout -> exported tree
    with prepare_local(
        LocalRequest(path=str(repo), mode="range", base="HEAD~1", head="HEAD~1")
    ) as ws:
        assert ws.workspace != repo
        assert "return 1" in (ws.workspace / "pkg" / "a.py").read_text()
    with prepare_local(LocalRequest(path=str(repo), mode="path", subpath="pkg")) as ws:
        assert [f.path for f in ws.changeset.files] == ["pkg/a.py"]


def test_prepare_local_rejects_non_git(tmp_path: Path) -> None:
    with (
        pytest.raises(GitError, match="not a git repository"),
        prepare_local(LocalRequest(path=str(tmp_path), mode="staged")),
    ):
        pass
    with pytest.raises(GitError, match="invalid ref"):
        export_tree(tmp_path, "--upload-pack=x", tmp_path / "o")
    with pytest.raises(GitError):
        rev_parse(tmp_path, "-x")


def test_list_files_and_collect_sources(repo: Path, tmp_path: Path) -> None:
    files = list_files(repo)
    assert "pkg/a.py" in files and not any(f.startswith("node_modules") for f in files)
    snap = collect_sources(repo, {".py"}, ["pkg/a.py", "missing.py"])
    assert list(snap.sources) == ["pkg/a.py"] and snap.total_bytes > 0
    limited = collect_sources(repo, {".py", ".js"}, [], max_files=0)
    assert limited.truncated and limited.sources == {}
    plain = tmp_path / "plain"
    (plain / "sub").mkdir(parents=True)
    (plain / "sub" / "b.py").write_text("x = 1\n")
    (plain / ".hidden").mkdir()
    (plain / ".hidden" / "c.py").write_text("")
    assert list_files(plain) == ["sub/b.py"]


# ----------------------------------------------------------------- caches


def test_caches(tmp_path: Path) -> None:
    key = content_key("a", "b")
    assert key == content_key("a", "b") != content_key("ab", "")
    mem = MemoryCache()
    assert mem.get("ns", key) is None
    mem.set("ns", key, "v")
    assert mem.get("ns", key) == "v" and (mem.hits, mem.misses) == (1, 1)
    disk = DiskCache(tmp_path / "cache", max_entry_bytes=10)
    disk.set("ns", key, "value")
    assert disk.get("ns", key) == "value"
    disk.set("ns", key, "x" * 100)  # too big: ignored, old value kept
    assert disk.get("ns", key) == "value"
    assert disk.get("ns", content_key("zzz")) is None
    with pytest.raises(ValueError, match="alphanumeric"):
        disk.get("../x", key)


# ----------------------------------------------------------------- observability


def test_log_formatters() -> None:
    record = logging.LogRecord("sentinel.x", logging.INFO, "f", 1, "stage done", (), None)
    record.stage = "ai_review"
    record.duration_ms = 42
    token = review_id_var.set("R-1")
    try:
        text = KeyValueFormatter().format(record)
        assert "stage done" in text and "stage=ai_review" in text and "review_id=R-1" in text
        data = json.loads(JsonFormatter().format(record))
        assert data["duration_ms"] == 42 and data["review_id"] == "R-1" and data["level"] == "info"
    finally:
        review_id_var.reset(token)
    try:
        raise RuntimeError("x")
    except RuntimeError:
        import sys

        rec = logging.LogRecord("s", logging.ERROR, "f", 1, "boom", (), sys.exc_info())
    assert "RuntimeError" in KeyValueFormatter().format(rec)
    assert "RuntimeError" in json.loads(JsonFormatter().format(rec))["exc"]
    configure_logging("json")
    assert isinstance(logging.getLogger("sentinel").handlers[0].formatter, JsonFormatter)
    configure_logging("text")


def test_metrics_render() -> None:
    m = Metrics()
    result = ReviewResult(
        changeset=ChangeSet(),
        status=ReviewStatus.COMPLETED,
        duration_ms=1234,
        stages=[StageRecord(name=StageName.AI_REVIEW, status=StageStatus.DONE, duration_ms=900)],
    )
    m.record_review(result)
    m.record_fix("validated", 5000)
    text = m.render()
    assert 'sentinel_reviews_total{status="completed"} 1' in text
    assert 'sentinel_stage_duration_ms_bucket{stage="ai_review",le="1000"} 1' in text
    assert "sentinel_review_duration_ms_count 1" in text
    assert 'sentinel_fix_attempts_total{status="validated"} 1' in text
    assert "# TYPE sentinel_review_duration_ms histogram" in text
