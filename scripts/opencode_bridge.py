"""Start, inspect or stop Sentinel's isolated local OpenCode fallback service.

Run with Sentinel installed: ``python scripts/opencode_bridge.py start --build``.
Only this trusted setup helper controls Docker; review/API workers use HTTP.
The generated token protects the local bridge and is unrelated to vendor API keys.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import time
from pathlib import Path

import httpx

from sentinel.core.configuration.config import load_settings, save_user_setting

IMAGE = "sentinel-opencode-bridge:1.19.3"
CONTAINER = "sentinel-opencode-bridge"
LABEL = "sentinel.opencode-bridge=1"
URL = "http://127.0.0.1:4097"


def docker(*arguments: str, env: dict[str, str] | None = None) -> str:
    """Run a fixed Docker operation without a shell; never print its environment."""
    result = subprocess.run(
        ["docker", *arguments],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Docker operation failed")
    return result.stdout.strip()


def exists() -> bool:
    """Find only the container created and labelled by this helper."""
    names = docker("ps", "-a", "--filter", f"name=^/{CONTAINER}$", "--format", "{{.Names}}")
    if not names:
        return False
    label = docker(
        "inspect", "--format", '{{index .Config.Labels "sentinel.opencode-bridge"}}', CONTAINER
    )
    if label != "1":
        raise RuntimeError("Container name belongs to another application; leaving it alone")
    return True


def healthy() -> bool:
    """Check the fixed loopback endpoint without using or displaying a secret."""
    try:
        response = httpx.get(URL + "/health", timeout=2, trust_env=False)
        return response.is_success and bool(response.json().get("ok"))
    except (httpx.HTTPError, ValueError):
        return False


def start(build: bool) -> None:
    """Install the trusted image if requested, then start it with no shared folders."""
    if build:
        context = Path(__file__).resolve().parents[1] / "tools" / "opencode_bridge"
        print("Building the isolated OpenCode image; project files and keys are excluded.")
        subprocess.run(["docker", "build", "-t", IMAGE, "."], cwd=context, check=True)
    settings = load_settings()
    token = settings.api_key_for("opencode")
    if not token:
        token = secrets.token_urlsafe(32)
        save_user_setting("opencode_token", token)
    if exists() and build:
        docker("stop", "--time", "5", CONTAINER)
        docker("rm", CONTAINER)
    if exists():
        docker("start", CONTAINER)
    else:
        _start_container(token)
    deadline = time.monotonic() + 30
    while not healthy():
        if time.monotonic() >= deadline:
            raise RuntimeError("Bridge did not become healthy; inspect Docker container status")
        time.sleep(0.25)
    save_user_setting("opencode_url", URL)
    print(
        "OpenCode bridge ready on this computer. Local token saved privately; no vendor key shared."
    )


def _start_container(token: str) -> None:
    environment = {**os.environ, "SENTINEL_OPENCODE_TOKEN": token}
    # WSL's Windows Docker launcher forwards only explicitly shared variables.
    if os.environ.get("WSL_DISTRO_NAME"):
        shared = environment.get("WSLENV", "")
        environment["WSLENV"] = shared + (":" if shared else "") + "SENTINEL_OPENCODE_TOKEN"
    docker(
        "run",
        "--pull=never",
        "-d",
        f"--name={CONTAINER}",
        f"--label={LABEL}",
        "--restart=unless-stopped",
        "--init",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs=/tmp:rw,nosuid,size=512m,mode=1777",
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=128",
        "-p",
        "127.0.0.1:4097:4097",
        "-e",
        "SENTINEL_OPENCODE_TOKEN",
        IMAGE,
        env=environment,
    )


def main() -> None:
    """Provide explicit lifecycle commands; starting does not itself enable fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--build", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.action == "start":
            start(arguments.build)
        elif arguments.action == "stop" and exists():
            docker("stop", "--time", "5", CONTAINER)
            docker("rm", CONTAINER)
            print("OpenCode bridge stopped and removed; image and private user setting retained.")
        else:
            print("OpenCode bridge is ready." if healthy() else "OpenCode bridge is not running.")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
