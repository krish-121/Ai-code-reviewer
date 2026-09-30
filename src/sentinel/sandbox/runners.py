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

import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path

from sentinel.core.domain.ports import SandboxResult
from sentinel.core.fixes.scratch import scratch_copy

__all__ = ["DockerSandbox", "ProcessSandbox", "scratch_copy"]

MAX_OUTPUT = 20_000


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n… (truncated)"


class DockerSandbox:
    isolation = "docker"

    def __init__(
        self,
        image: str = "sentinel-sandbox:latest",
        *,
        memory: str = "1g",
        cpus: str = "1.0",
        pids: int = 256,
        docker: str = "docker",
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids = pids
        self.docker = docker

    def is_available(self) -> bool:
        exe = shutil.which(self.docker)
        if exe is None:
            return False
        try:
            probe = subprocess.run(
                [exe, "image", "inspect", self.image], capture_output=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return probe.returncode == 0

    def command(self, workspace: Path, command: list[str], name: str, network: bool) -> list[str]:
        uid, gid = os.getuid(), os.getgid()
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
            "/tmp:rw,exec,size=256m",  # noqa: S108 - tmpfs inside the container
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
            "-v",
            f"{workspace.resolve()}:/workspace:rw",
            "-w",
            "/workspace",
            self.image,
            *command,
        ]

    def run(
        self, workspace: Path, command: list[str], timeout_s: int = 120, *, network: bool = False
    ) -> SandboxResult:
        name = f"sentinel-sbx-{uuid.uuid4().hex[:12]}"
        cmd = self.command(workspace, command, name, network)
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker, "kill", name], capture_output=True, check=False)
            return SandboxResult(
                command=command,
                exit_code=-1,
                stdout=_truncate(_text(exc.stdout)),
                stderr="timed out",
                duration_ms=int((time.monotonic() - start) * 1000),
                timed_out=True,
                isolation=self.isolation,
            )
        return SandboxResult(
            command=command,
            exit_code=proc.returncode,
            stdout=_truncate(proc.stdout),
            stderr=_truncate(proc.stderr),
            duration_ms=int((time.monotonic() - start) * 1000),
            isolation=self.isolation,
        )


def _text(data: object) -> str:
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data if isinstance(data, str) else ""


@lru_cache(maxsize=1)
def _netns_available() -> bool:
    exe = shutil.which("unshare")
    if exe is None:
        return False
    try:
        probe = subprocess.run(
            [exe, "--user", "--map-root-user", "--net", "true"], capture_output=True, timeout=10
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
        return True

    def run(
        self, workspace: Path, command: list[str], timeout_s: int = 120, *, network: bool = False
    ) -> SandboxResult:
        home = Path(tempfile.mkdtemp(prefix="sentinel-home-"))
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CI": "1",
        }
        for key in ("PYTHONPATH", "NODE_PATH", "VIRTUAL_ENV"):
            if key in os.environ:
                env[key] = os.environ[key]
        cmd = list(command)
        if self.netns and not network:
            cmd = ["unshare", "--user", "--map-root-user", "--net", "--", *cmd]
        limits = (self.memory_bytes, self.max_file_bytes, timeout_s)

        def _preexec() -> None:  # pragma: no cover - runs in the child
            import resource

            os.setsid()
            mem, fsize, cpu = limits
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu + 5, cpu + 10))

        start = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=_preexec,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            timed_out = True
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
