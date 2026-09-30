"""Shared plumbing for static-analysis adapters.

Every adapter turns tool output into normalized ``Finding`` objects with
``source=STATIC_ANALYZER`` and an ``origins`` entry like ``ruff:S608``. A missing tool is
not an error: the run is recorded as ``unavailable`` and the review carries on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from sentinel.core.domain.models import (
    AnalysisRun,
    Category,
    Evidence,
    Finding,
    FindingSource,
    Severity,
)

SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "TMPDIR",
    "NODE_PATH",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "MYPY_CACHE_DIR",
)


@dataclass
class ToolResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def find_tool(name: str, workspace: Path | None = None) -> str | None:
    """Prefer a project-local install (node_modules/.bin, .venv/bin), then PATH."""
    if workspace is not None:
        for local in (
            workspace / "node_modules" / ".bin" / name,
            workspace / ".venv" / "bin" / name,
            workspace / "venv" / "bin" / name,
        ):
            if local.is_file() and os.access(local, os.X_OK):
                return str(local)
    return shutil.which(name)


def scrubbed_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Tools never need API keys or tokens; don't hand them any."""
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
    env.update(extra or {})
    return env


def run_tool(cmd: list[str], cwd: Path, timeout_s: int, stdin: str | None = None) -> ToolResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=scrubbed_env(),
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return ToolResult(-1, out, "timeout", int((time.monotonic() - start) * 1000), True)
    return ToolResult(
        proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - start) * 1000)
    )


def run_record(
    tool: str, result: ToolResult | None, findings: int, detail: str = ""
) -> AnalysisRun:
    if result is None:
        return AnalysisRun(tool=tool, status="unavailable", detail=detail)
    status = "timeout" if result.timed_out else "ok"
    return AnalysisRun(
        tool=tool, status=status, duration_ms=result.duration_ms, findings=findings, detail=detail
    )


def static_finding(
    *,
    tool: str,
    rule: str,
    category: Category,
    severity: Severity,
    confidence: float,
    title: str,
    file: str,
    line: int,
    end_line: int | None = None,
    explanation: str = "",
    tags: list[str] | None = None,
    suggested_fix: str | None = None,
    evidence: str | None = None,
) -> Finding:
    line = max(1, line)
    return Finding(
        category=category,
        severity=severity,
        confidence=confidence,
        title=title,
        explanation=explanation or title,
        file=file,
        line_start=line,
        line_end=max(line, end_line or line),
        evidence=[
            Evidence(source=tool, text=evidence or f"{tool} {rule}: {title}", file=file, line=line)
        ],
        suggested_fix=suggested_fix,
        source=FindingSource.STATIC_ANALYZER,
        origins=[f"{tool}:{rule}"],
        rule_id=f"{tool}/{rule}",
        tags=tags or [],
    )


def relpath(path: str, workspace: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    return p.as_posix().removeprefix("./")
