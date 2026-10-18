"""Exercise an isolated full Compose deployment and always remove its disposable data.

Builds production images, adds a deterministic Ollama HTTP fixture, drives the real
API/queue/workers/Docker validation/Apply, then recreates services to check persistence.
This script never selects an existing Compose project or reads the operator's .env.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/deployment"
POLL_TIMEOUT_S = 240


class Acceptance:
    """Own one unique Compose project, with commands and results kept for diagnosis."""

    def __init__(self, docker: str, output: Path, temporary: Path) -> None:
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.project = "sentinel-acceptance-" + uuid.uuid4().hex[:10]
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("SENTINEL_") and key not in {"POSTGRES_PASSWORD", "DOCKER_GID"}
        }
        settings = {
            "SENTINEL_PROVIDER": "ollama",
            "SENTINEL_MODEL": "compose-fixture",
            "SENTINEL_OLLAMA_URL": "http://provider-fixture:11434",
            "SENTINEL_LOCAL_ROOTS": "/repos",
            "POSTGRES_PASSWORD": "disposable" + uuid.uuid4().hex,
            "SENTINEL_BIND_PORT": "0",
            "SENTINEL_APP_IMAGE": "sentinel-compose-check:app",
            "SENTINEL_VALIDATION_IMAGE": "sentinel-compose-check:validation-worker",
            "SENTINEL_SANDBOX_IMAGE": "sentinel-sandbox:compose-check",
            "DOCKER_GID": str(
                os.stat("/var/run/docker.sock").st_gid
                if Path("/var/run/docker.sock").exists()
                else 0
            ),
        }
        env_file = temporary / "acceptance.env"
        env_file.write_text("\n".join(f"{key}={value}" for key, value in settings.items()) + "\n")
        self.env.update(settings, SENTINEL_ENV_FILE=str(env_file))
        override = temporary / "compose.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "provider-fixture": {
                            "image": settings["SENTINEL_APP_IMAGE"],
                            "command": ["python", "-u", "-c", (FIXTURES / "ollama.py").read_text()],
                            "read_only": True,
                            "cap_drop": ["ALL"],
                            "security_opt": ["no-new-privileges:true"],
                        }
                    }
                }
            )
        )
        self.base = [
            docker,
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(env_file),
            "-f",
            str(REPO / "docker-compose.yml"),
            "-f",
            str(override),
        ]
        self.token = ""
        self.port = 0
        self.results: dict[str, Any] = {"project": self.project}

    def compose(
        self, *args: str, timeout: int = 300, private: bool = False, expect_failure: bool = False
    ) -> str:
        """Run one command, preserving diagnostics without printing the test user's token."""
        if args[0] == "build":
            with (self.output / "build.log").open("w", encoding="utf-8") as build_log:
                result = subprocess.run(
                    [*self.base, *args],
                    cwd=REPO,
                    env=self.env,
                    stdout=build_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
        else:
            result = subprocess.run(
                [*self.base, *args],
                cwd=REPO,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        with (self.output / "commands.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps(list(args)) + f" -> {result.returncode}\n")
            if not private:
                log.write(
                    re.sub(
                        r"snt_[A-Za-z0-9_-]+",
                        "[test-token]",
                        (result.stdout or "") + (result.stderr or ""),
                    )
                    + "\n"
                )
        if (result.returncode != 0) != expect_failure:
            raise RuntimeError(f"Compose {args[0]} failed; see {self.output / 'commands.log'}")
        return result.stdout or ""

    def request(self, path: str, body: dict[str, Any] | None = None, *, expected: int = 200) -> Any:
        """Make a real authenticated HTTP request to the loopback test deployment."""
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "X-Sentinel-Client": "compose-acceptance",
        }
        data = json.dumps(body).encode() if body is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(
                "POST" if body is not None else "GET", path, body=data, headers=headers
            )
            response = connection.getresponse()
            payload = response.read()
            if response.status != expected:
                raise RuntimeError(f"{path}: HTTP {response.status}: {payload.decode()}")
            if "application/json" in (response.getheader("Content-Type") or ""):
                return json.loads(payload)
            return payload.decode()
        finally:
            connection.close()

    def wait(self, path: str, running: set[str]) -> Any:
        """Wait for a queued operation with a bounded deadline."""
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            result = self.request(path)
            if result["status"] not in running:
                return result
            time.sleep(0.5)
        raise TimeoutError(f"operation did not finish: {path}")

    def verify(self, *, build: bool) -> None:
        """Check deployment boundaries, then a complete review/fix/persistence workflow."""
        password = self.env["POSTGRES_PASSWORD"]
        try:
            self.env["POSTGRES_PASSWORD"] = ""
            self.compose("config", "--quiet", expect_failure=True)
        finally:
            self.env["POSTGRES_PASSWORD"] = password
        self.results["missing_database_password_rejected"] = True
        config = json.loads(self.compose("config", "--format", "json"))
        for name in ("api", "worker"):
            assert all(
                mount["target"] != "/var/run/docker.sock"
                for mount in config["services"][name].get("volumes", [])
            )
        assert (
            config["services"]["validation-worker"]["environment"]["SENTINEL_SANDBOX_TRANSPORT"]
            == "copy"
        )
        if build:
            self.compose("build", timeout=1800)
        self.compose("up", "-d", "--wait", "--wait-timeout", "180", timeout=240)
        self.port = int(self.compose("port", "api", "8000").strip().rsplit(":", 1)[1])
        assert self.request("/api/health")["database"] == "postgresql"
        assert "app.js" in self.request("/")
        assert len(self.request("/assets/app.js")) > 10_000
        self.request("/api/reviews", expected=401)
        user = json.loads(
            self.compose(
                "exec",
                "-T",
                "api",
                "python",
                "-I",
                "-c",
                (FIXTURES / "initialize.py").read_text(),
                private=True,
            )
        )
        self.token = user["token"]
        review_id = self.request(
            "/api/reviews", {"path": "/repos/acceptance", "mode": "path"}, expected=202
        )["id"]
        detail = self.wait(f"/api/reviews/{review_id}", {"queued", "running"})
        assert detail["status"] == "completed", detail
        runs = detail["analysis_runs"]
        assert {run["tool"] for run in runs} == {
            "sentinel",
            "ruff",
            "mypy",
            "bandit",
            "eslint",
            "tsc",
        }
        assert all(run["status"] == "ok" for run in runs), runs
        findings = self.request(f"/api/reviews/{review_id}/findings")
        eslint = {finding["file"] for finding in findings if "eslint:no-eval" in finding["origins"]}
        assert eslint == {"unsafe.js", "unsafe.ts"}, findings
        sql = next(
            finding for finding in findings if finding.get("rule_id") == "sentinel/sql-injection"
        )
        assert self.request(f"/api/reviews/{review_id}/graph")["nodes"]
        assert "event: done" in self.request(f"/api/reviews/{review_id}/events")
        fix_id = self.request(f"/api/findings/{sql['id']}/fix", {}, expected=202)["id"]
        fix = self.wait(f"/api/fixes/{fix_id}", {"queued", "running"})
        assert fix["status"] == "validated" and fix["isolation"] == "docker", fix
        assert any(
            check["name"] == "regression-tests" and check["status"] == "passed"
            for check in fix["checks"]
        )
        applied = self.request(f"/api/fixes/{fix_id}/apply", {})
        assert applied["applied"] == ["helper.py", "query.py", "test_query_regression.py"]
        assert "sentinel_reviews_total" in self.request("/metrics")
        self.results.update(
            review_id=review_id,
            fix_id=fix_id,
            analysis_runs=runs,
            checks=fix["checks"],
            applied=applied["applied"],
            http_auth_ui_sse_metrics="passed",
        )
        self._verify_restart(review_id, fix_id)
        self.results["status"] = "passed"
        (self.output / "results.json").write_text(json.dumps(self.results, indent=2))

    def _verify_restart(self, review_id: str, fix_id: str) -> None:
        self.compose("stop", "api", "worker", "validation-worker", "postgres")
        self.compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180", timeout=240)
        self.port = int(self.compose("port", "api", "8000").strip().rsplit(":", 1)[1])
        assert self.request(f"/api/reviews/{review_id}")["status"] == "completed"
        assert self.request(f"/api/fixes/{fix_id}")["status"] == "applied"
        state = self.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-I",
            "-c",
            "from pathlib import Path; p=Path('/repos/acceptance'); "
            "assert \"'safe'\" in (p/'helper.py').read_text(); "
            "assert 'WHERE name = ?' in (p/'query.py').read_text(); "
            "assert (p/'test_query_regression.py').is_file(); print('repository files persisted')",
        )
        assert "persisted" in state
        self.results["restart_and_persistence"] = "passed"

    def cleanup(self) -> None:
        """Collect owned-project logs, then remove only its disposable containers/volumes."""
        try:
            (self.output / "services.log").write_text(
                self.compose("logs", "--no-color"), encoding="utf-8"
            )
        finally:
            self.compose("down", "--volumes", "--remove-orphans")


def main() -> None:
    """Run the opt-in integration rehearsal and retain a compact evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sentinel-compose-check-") as directory:
        check = Acceptance(args.docker, args.output.resolve(), Path(directory))
        try:
            check.verify(build=not args.no_build)
        finally:
            check.cleanup()
    print(json.dumps(check.results, indent=2))


if __name__ == "__main__":
    main()
