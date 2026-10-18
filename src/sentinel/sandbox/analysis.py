"""Run fix analysis only in the trusted, installed Docker image."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import AnalysisRun, Finding, ToolStatus
from sentinel.core.fixes.validation import Sandbox
from sentinel.sandbox.runners import MAX_REPORT_OUTPUT, DockerSandbox


class AnalysisReport(BaseModel):
    """The container's analysis response; malformed/truncated output is not success."""

    findings: list[Finding]
    runs: list[AnalysisRun]


class SandboxStaticRunner:
    """Static analysis of generated files, with no project tools executed on the host."""

    isolation = "docker"

    def __init__(self, sandbox: Sandbox | None, config: RepoConfig) -> None:
        self.sandbox = sandbox
        self.config = config

    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]:
        """Invoke an isolated Python entry point installed in the image, never the mount."""
        if (
            self.sandbox is None
            or self.sandbox.isolation != "docker"
            or not self.sandbox.is_available()
        ):
            return [], [AnalysisRun(tool="sandbox-static", status=ToolStatus.UNAVAILABLE)]
        command = [
            "python",
            "-I",
            "-m",
            "sentinel.sandbox.analyze",
            json.dumps(files),
            json.dumps(self.config.static.disabled),
            str(self.config.static.timeout_s),
        ]
        timeout = self.config.static.timeout_s + 30
        # Structured reports need more room than human-facing test logs. Keep both bounded.
        if isinstance(self.sandbox, DockerSandbox):
            result = self.sandbox.run(workspace, command, timeout, output_limit=MAX_REPORT_OUTPUT)
        else:
            result = self.sandbox.run(workspace, command, timeout)
        if result.ok:
            try:
                report = AnalysisReport.model_validate_json(result.stdout)
                return report.findings, report.runs
            except ValidationError:
                pass
        status = ToolStatus.TIMEOUT if result.timed_out else ToolStatus.FAILED
        return [], [
            AnalysisRun(
                tool="sandbox-static",
                status=status,
                detail="container analysis failed or returned invalid output"
                + (
                    ": output limit reached"
                    if "truncated" in result.stdout or "output limit" in result.stderr
                    else ""
                ),
            )
        ]
