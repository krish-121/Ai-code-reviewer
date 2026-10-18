"""Sandboxes: isolation flags and a real Docker run when available."""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

import pytest

from sentinel.bootstrap import build_sandbox
from sentinel.core.configuration.config import Settings
from sentinel.sandbox.runners import DockerSandbox, ProcessSandbox

DOCKER = DockerSandbox(
    image=os.environ.get("SENTINEL_TEST_SANDBOX_IMAGE", "sentinel-sandbox:latest"),
    transport="copy" if os.environ.get("SENTINEL_TEST_DOCKER_COPY") == "1" else "bind",
)
HAS_DOCKER = DOCKER.is_available()


def test_process_sandbox_basics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_CLAUDE_KEY", "sk-secret")
    sb = ProcessSandbox()
    res = sb.run(
        tmp_path, ["python3", "-c", "import os; print(os.environ.get('SENTINEL_CLAUDE_KEY'))"]
    )
    assert res.ok and res.stdout.strip() == "None"  # host secrets are not inherited
    fail = sb.run(tmp_path, ["python3", "-c", "raise SystemExit(3)"])
    assert fail.exit_code == 3 and not fail.ok
    slow = sb.run(tmp_path, ["python3", "-c", "import time; time.sleep(30)"], timeout_s=1)
    assert slow.timed_out and not slow.ok


def test_process_sandbox_blocks_network_when_possible(tmp_path: Path) -> None:
    sb = ProcessSandbox()
    if not sb.netns:
        pytest.skip("user/network namespaces unavailable here")
    code = (
        "import socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 80), timeout=2)\n    print('open')\n"
        "except OSError:\n    print('blocked')\n"
    )
    res = sb.run(tmp_path, ["python3", "-c", code])
    assert res.stdout.strip() == "blocked"
    assert sb.isolation == "process+netns"


def test_docker_command_is_locked_down(tmp_path: Path) -> None:
    cmd = DockerSandbox().command(tmp_path, ["pytest"], "sbx", network=False)
    joined = " ".join(cmd)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges",
        "--pids-limit",
        "--memory",
        "--cpus",
    ):
        assert flag in joined
    assert f"{tmp_path.resolve()}:/workspace:rw" in joined
    assert "--network bridge" in " ".join(DOCKER.command(tmp_path, ["x"], "n", network=True))
    assert not DockerSandbox(docker="definitely-not-docker").is_available()


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_docker_sandbox_runs_isolated(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    res = DOCKER.run(tmp_path, ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    assert res.ok, res.stdout + res.stderr
    net = DOCKER.run(
        tmp_path, ["python", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), 2)"]
    )
    assert not net.ok and "unreachable" in (net.stderr + net.stdout).lower()
    ro = DOCKER.run(tmp_path, ["python", "-c", "open('/etc/pwned', 'w')"])
    assert not ro.ok
    slow = DOCKER.run(tmp_path, ["python", "-c", "import time; time.sleep(30)"], timeout_s=2)
    assert slow.timed_out


def test_build_sandbox_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DockerSandbox, "is_available", lambda self: False)
    assert build_sandbox(Settings()) is None  # no silent downgrade to weaker isolation
    assert isinstance(build_sandbox(Settings(allow_process_sandbox=True)), ProcessSandbox)
    monkeypatch.setattr(DockerSandbox, "is_available", lambda self: True)
    assert isinstance(build_sandbox(Settings()), DockerSandbox)
    assert os.environ.get("SENTINEL_ALLOW_PROCESS_SANDBOX") is None


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_packaged_demo_fix_completes_all_required_checks(tmp_path: Path) -> None:
    from sentinel.bootstrap import build_fix_engine
    from sentinel.core.configuration.config import load_repo_config
    from tests.fakes import ScriptedProvider
    from tests.unit.test_fix_engine import FIXED, VULN, fix_payload, sqli_finding

    # Reuse the real demo builder; the repository under test is always disposable.
    builder_path = Path(__file__).resolve().parents[2] / "demo/build_demo_repo.py"
    spec = importlib.util.spec_from_file_location("sentinel_demo_builder", builder_path)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    root = builder.build(tmp_path / "demo")
    ai = ScriptedProvider(fixes=[fix_payload(VULN, FIXED)])
    settings = Settings(cache_dir=tmp_path / "cache")
    engine = build_fix_engine(
        settings, load_repo_config(root), workspace=root, ai=ai, sandbox=DOCKER
    )
    result = engine.generate(sqli_finding(), root)
    assert result.status == "validated", result.checks
    assert all(check.status == "passed" for check in result.checks)
    assert VULN in (root / "app/db.py").read_text()


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_report_output_budget_preserves_structured_data_without_widening_test_logs(
    tmp_path: Path,
) -> None:
    command = ["python", "-c", "import json; print(json.dumps({'data': 'x' * 25000}))"]
    normal = DOCKER.run(tmp_path, command)
    assert "truncated" in normal.stdout
    report = DOCKER.run(tmp_path, command, output_limit=60_000)
    assert report.ok
    import json

    assert len(json.loads(report.stdout)["data"]) == 25_000


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_fix_analysis_and_tests_use_trusted_container_tools(tmp_path: Path) -> None:
    from sentinel.bootstrap import build_fix_engine
    from sentinel.core.configuration.config import RepoConfig
    from sentinel.core.domain.models import Category, Finding, FindingSource, Severity
    from tests.fakes import ScriptedProvider

    root = tmp_path / "repo"
    root.mkdir()
    marker = tmp_path / "host-executed"
    (root / "mypy.ini").write_text("[mypy]\nplugins = evil.py\n")
    (root / "evil.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    before = "    return cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n"
    after = '    return cur.execute("SELECT * FROM users WHERE name = ?", (name,))\n'
    (root / "query.py").write_text("def query(cur, name):\n" + before)
    (root / "test_query.py").write_text(
        "import yaml\nfrom query import query\nclass Cursor:\n"
        "    def execute(self, sql, *args):\n        return sql\n"
        "def test_query():\n    assert query(Cursor(), yaml.safe_load('name')).startswith('SELECT')\n"
    )
    ai = ScriptedProvider(
        fixes=[
            {
                "summary": "parameterize",
                "edits": [{"file": "query.py", "search": before, "replace": after}],
            }
        ]
    )
    engine = build_fix_engine(Settings(), RepoConfig(), workspace=root, ai=ai, sandbox=DOCKER)
    finding = Finding(
        category=Category.SECURITY,
        severity=Severity.HIGH,
        confidence=0.9,
        source=FindingSource.STATIC_ANALYZER,
        title="SQL injection",
        explanation="interpolated SQL",
        file="query.py",
        line_start=2,
        line_end=2,
        origins=["sentinel:sql-injection"],
        tags=["sql-injection"],
    )
    result = engine.generate(finding, root)
    assert result.status == "validated", result.checks
    assert not marker.exists()
    assert (root / "query.py").read_text() == "def query(cur, name):\n" + before


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_s22_trusted_python_and_node_dependencies_without_host_links(tmp_path: Path) -> None:
    from sentinel.core.fixes.scratch import scratch_copy

    root = tmp_path / "repo"
    root.mkdir()
    host_modules = root / "node_modules"
    host_modules.mkdir()
    marker = host_modules / "host-marker"
    marker.write_text("untouched")
    scratch = scratch_copy(root)
    try:
        assert not (scratch / "node_modules").exists()
        python = DOCKER.run(
            scratch,
            [
                "python",
                "-I",
                "-c",
                "import yaml; assert yaml.safe_load('answer: 42')['answer'] == 42",
            ],
        )
        node = DOCKER.run(
            scratch,
            [
                "node",
                "-e",
                "const ts=require('typescript'); if (!ts.version.startsWith('5.')) process.exit(1)",
            ],
        )
        assert python.exit_code == 0, python.stderr
        assert node.exit_code == 0, node.stderr
        assert marker.read_text() == "untouched"
    finally:
        shutil.rmtree(scratch)


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_multi_file_fix_and_created_test_validate_in_real_docker(tmp_path: Path) -> None:
    from sentinel.bootstrap import build_fix_engine
    from sentinel.core.configuration.config import RepoConfig
    from sentinel.core.fixes.engine import apply_fix
    from tests.fakes import ScriptedProvider
    from tests.unit.test_multi_file_fixes import BEFORE, TEST, issue, proposal

    root = tmp_path / "repo"
    root.mkdir()
    (root / "query.py").write_text("from helper import label\ndef query(cur, name):\n" + BEFORE)
    (root / "helper.py").write_text("def label():\n    return 'unsafe'\n")
    ai = ScriptedProvider(fixes=[proposal(), proposal()])
    engine = build_fix_engine(Settings(), RepoConfig(), workspace=root, ai=ai, sandbox=DOCKER)
    result = engine.generate(issue(), root)
    assert result.status == "validated", result.checks
    assert any(c.name == "regression-tests" and c.status == "passed" for c in result.checks)
    assert not (root / "test_query_regression.py").exists()
    assert BEFORE in (root / "query.py").read_text()
    assert apply_fix(root, result) == ["helper.py", "query.py", "test_query_regression.py"]
    assert (root / "test_query_regression.py").read_text() == TEST


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="docker daemon or sentinel-sandbox image unavailable")
def test_copy_transport_uses_private_tmpfs_without_host_paths(tmp_path: Path) -> None:
    sandbox = DockerSandbox(image=DOCKER.image, docker=DOCKER.docker, transport="copy")
    (tmp_path / "empty").mkdir()
    (tmp_path / "input.txt").write_text("original")
    (tmp_path / ".env").write_text("SECRET=never")
    result = sandbox.run(
        tmp_path,
        [
            "python",
            "-I",
            "-c",
            "from pathlib import Path; import os; "
            "assert not Path('.env').exists(); assert not Path('/var/run/docker.sock').exists(); "
            "assert Path('empty').is_dir(); "
            "assert os.getuid() != 0; assert not os.environ.get('SENTINEL_CLAUDE_KEY'); "
            "p=Path('input.txt'); assert p.read_text()=='original'; p.write_text('scratch only'); "
            "print('copy-isolated')",
        ],
    )
    assert result.ok and result.stdout.strip() == "copy-isolated", result.stderr
    assert (tmp_path / "input.txt").read_text() == "original"
    assert sandbox.run(
        tmp_path, ["python", "-c", "import time; time.sleep(30)"], timeout_s=1
    ).timed_out
