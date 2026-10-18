"""Sandboxes for running AI-generated code (tests of a proposed fix).

``DockerSandbox`` is the default and the only one considered safe: no network, capped
memory/CPU/PIDs, read-only root filesystem, all capabilities dropped, a throwaway copy
of the repository mounted as the working directory, and a hard timeout.

``ProcessSandbox`` exists for machines without Docker and must be explicitly enabled
(``SENTINEL_ALLOW_PROCESS_SANDBOX=1``). It runs on the host in a scratch copy with a
scrubbed environment, rlimits, its own process group, and — where the kernel allows —
a private network namespace. It reports its isolation level honestly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path
from typing import Literal

from sentinel.core.domain.ports import SandboxResult
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.sandbox.output import communicate_capped
from sentinel.sandbox.workspace import pack_workspace

__all__ = ["DockerSandbox", "ProcessSandbox", "scratch_copy"]

MAX_OUTPUT = 20_000
MAX_REPORT_OUTPUT = 1_048_576
DEFAULT_IMAGE = "sentinel-sandbox:latest"
DEFAULT_TIMEOUT_S = 120
DOCKER_PROBE_TIMEOUT_S = 15
NETNS_PROBE_TIMEOUT_S = 10
CONTAINER_TMPFS = "/tmp:rw,exec,size=256m"  # noqa: S108 - tmpfs inside the container
CONTAINER_WORKDIR = "/workspace"
# CPU-time limit for the process sandbox: soft/hard seconds beyond the wall-clock timeout.
CPU_SOFT_GRACE_S, CPU_HARD_GRACE_S = 5, 10
PASSTHROUGH_ENV = ("PYTHONPATH", "NODE_PATH", "VIRTUAL_ENV")
UNSHARE_NETWORK = ["unshare", "--user", "--map-root-user", "--net"]


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    """Cap captured output so a noisy test run cannot fill the database."""
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


class DockerSandbox:
    """Runs commands in a locked-down, throwaway Docker container (the default sandbox)."""

    isolation = "docker"

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        *,
        memory: str = "1g",
        cpus: str = "1.0",
        pids: int = 256,
        docker: str = "docker",
        transport: Literal["bind", "copy"] = "bind",
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids = pids
        self.docker = docker
        self.transport = transport

    def is_available(self) -> bool:
        """True when the Docker CLI works and the sandbox image exists locally."""
        exe = shutil.which(self.docker)
        if exe is None:
            return False
        try:
            probe = subprocess.run(
                [exe, "image", "inspect", self.image],
                capture_output=True,
                timeout=DOCKER_PROBE_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return probe.returncode == 0

    def command(self, workspace: Path, command: list[str], name: str, network: bool) -> list[str]:
        """The full ``docker run`` command line, one isolation option per pair of lines."""
        uid, gid = os.getuid(), os.getgid()
        mount = ["-v", f"{workspace.resolve()}:{CONTAINER_WORKDIR}:rw"]
        invocation = command
        if self.transport == "copy":
            mount = ["-i", "--tmpfs", f"/workspace:rw,exec,size=512m,uid={uid},gid={gid},mode=0700"]
            invocation = ["python", "-I", "-m", "sentinel.sandbox.launch", json.dumps(command)]
        return [
            self.docker,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "bridge" if network else "none",
            "--memory",
            self.memory,
            "--memory-swap",
            self.memory,
            "--cpus",
            self.cpus,
            "--pids-limit",
            str(self.pids),
            "--read-only",
            "--tmpfs",
            CONTAINER_TMPFS,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{uid}:{gid}",
            "-e",
            "HOME=/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "CI=1",
            *mount,
            "-w",
            CONTAINER_WORKDIR,
            self.image,
            *invocation,
        ]

    def run(
        self,
        workspace: Path,
        command: list[str],
        timeout_s: int = DEFAULT_TIMEOUT_S,
        *,
        network: bool = False,
        output_limit: int = MAX_OUTPUT,
    ) -> SandboxResult:
        """Run on a scratch bind or transferred tmpfs copy; kill the container on timeout."""
        if not 0 < output_limit <= MAX_REPORT_OUTPUT:
            raise ValueError("sandbox output limit is outside the supported bounds")
        name = f"sentinel-sbx-{uuid.uuid4().hex[:12]}"
        cmd = self.command(workspace, command, name, network)
        start = time.monotonic()

        def cleanup() -> None:
            subprocess.run(
                [self.docker, "kill", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )

        with ExitStack() as stack:
            stdin = None
            if self.transport == "copy":
                stdin = stack.enter_context(tempfile.TemporaryFile())
                pack_workspace(workspace, stdin)
                stdin.seek(0)
            proc = subprocess.Popen(
                cmd,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            out, err, timed_out = communicate_capped(
                proc, timeout_s, cleanup, max_bytes=output_limit * 2
            )
        return SandboxResult(
            command=command,
            exit_code=-1 if timed_out else proc.returncode,
            stdout=_truncate(out, output_limit),
            stderr=_truncate("timed out" if timed_out else err, output_limit),
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
            isolation=self.isolation,
        )


def _text(data: object) -> str:
    """Captured output as text (``TimeoutExpired`` may hold bytes)."""
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data if isinstance(data, str) else ""


@lru_cache(maxsize=1)
def _netns_available() -> bool:
    """True when unprivileged network namespaces work here (checked once)."""
    exe = shutil.which("unshare")
    if exe is None:
        return False
    try:
        probe = subprocess.run(
            [exe, *UNSHARE_NETWORK[1:], "true"], capture_output=True, timeout=NETNS_PROBE_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


class ProcessSandbox:
    """Reduced isolation. Opt-in only; see module docstring."""

    def __init__(self, *, memory_bytes: int = 2 * 1024**3, max_file_bytes: int = 200 * 1024**2):
        self.memory_bytes = memory_bytes
        self.max_file_bytes = max_file_bytes
        self.netns = _netns_available()
        self.isolation = "process+netns" if self.netns else "process"

    def is_available(self) -> bool:
        """Always available (it only needs a process)."""
        return True

    def run(
        self,
        workspace: Path,
        command: list[str],
        timeout_s: int = DEFAULT_TIMEOUT_S,
        *,
        network: bool = False,
    ) -> SandboxResult:
        """Run ``command`` in its own process group with resource limits and a clean env."""
        home = Path(tempfile.mkdtemp(prefix="sentinel-home-"))
        cmd = [*UNSHARE_NETWORK, "--", *command] if self.netns and not network else list(command)
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=workspace,
                env=_scrubbed_env(home),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=_limits_setter(self.memory_bytes, self.max_file_bytes, timeout_s),
            )
            out, err, timed_out = communicate_capped(proc, timeout_s)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        return SandboxResult(
            command=command,
            exit_code=-1 if timed_out else proc.returncode,
            stdout=_truncate(out),
            stderr=_truncate(err if not timed_out else "timed out"),
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
            isolation=self.isolation,
        )


def _scrubbed_env(home: Path) -> dict[str, str]:
    """A minimal environment: no API keys or tokens from the parent process leak in."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CI": "1",
    }
    env.update({key: os.environ[key] for key in PASSTHROUGH_ENV if key in os.environ})
    return env


def _limits_setter(memory_bytes: int, max_file_bytes: int, timeout_s: int) -> Callable[[], None]:
    """A ``preexec_fn`` that runs in the child: new session + memory/file/CPU rlimits."""

    def set_limits() -> None:  # pragma: no cover - runs in the child process
        import resource

        os.setsid()
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))
        resource.setrlimit(
            resource.RLIMIT_CPU, (timeout_s + CPU_SOFT_GRACE_S, timeout_s + CPU_HARD_GRACE_S)
        )

    return set_limits
