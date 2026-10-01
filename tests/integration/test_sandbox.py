"""Sandboxes: isolation flags and a real Docker run when available."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sentinel.bootstrap import build_sandbox
from sentinel.core.configuration.config import Settings
from sentinel.sandbox.runners import DockerSandbox, ProcessSandbox

DOCKER = DockerSandbox()
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
    cmd = DOCKER.command(tmp_path, ["pytest"], "sbx", network=False)
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
