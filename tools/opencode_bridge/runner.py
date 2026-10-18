"""Run the official OpenCode CLI inside the bridge container, never on its host.

The HTTP server calls this bounded runner with already validated prompt text. Input
uses stdin, not a shell or process arguments. OpenCode has no project mounts or
vendor credentials; noninteractive permission requests must be rejected.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from typing import Any

MODEL = "deepseek-v4.1-flash-free"
MAX_CONTEXT_TOKENS = 131_072
MAX_OUTPUT_BYTES = 1_048_576
TIMEOUT_S = 75.0
POLL_S = 0.05


class BridgeError(Exception):
    """A bounded, non-secret error that can be returned to the local caller."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def run_opencode(prompt: str, max_tokens: int = 4096, temperature: float = 0.1) -> dict[str, Any]:
    """Run one isolated CLI session and return an ordinary completion envelope."""
    command = [
        "opencode",
        "run",
        "--format",
        "json",
        "--agent",
        "build",
        "--model",
        f"opencode/{MODEL}",
        "--title",
        "Sentinel review",
    ]
    with (
        tempfile.TemporaryDirectory(prefix="sentinel-opencode-") as session,
        tempfile.TemporaryFile() as source,
        tempfile.TemporaryFile() as output,
        tempfile.TemporaryFile() as errors,
    ):
        environment = _environment(session, max_tokens, temperature)
        source.write(prompt.encode("utf-8"))
        source.seek(0)
        with subprocess.Popen(
            command,
            stdin=source,
            stdout=output,
            stderr=errors,
            env=environment,
            cwd=session,
            start_new_session=True,
        ) as process:
            try:
                _wait(process, output.fileno(), errors.fileno())
            finally:
                # Kill descendants too, including a child waiting for approval.
                _kill_group(process.pid)
            output.seek(0)
            return parse_events(output.read(MAX_OUTPUT_BYTES).decode("utf-8"), process.returncode)


def _environment(session: str, max_tokens: int, temperature: float) -> dict[str, str]:
    # Never inherit the bridge's local bearer token into the model client or tools.
    environment = {k: v for k, v in os.environ.items() if k != "SENTINEL_OPENCODE_TOKEN"}
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(
        {
            "agent": {"build": {"temperature": temperature}},
            "provider": {
                "opencode": {
                    "models": {
                        MODEL: {
                            "limit": {"context": MAX_CONTEXT_TOKENS, "output": max_tokens},
                        }
                    }
                }
            },
        }
    )
    for kind in ("CONFIG", "DATA", "CACHE", "STATE"):
        environment[f"XDG_{kind}_HOME"] = f"{session}/{kind.lower()}"
    return environment


def _kill_group(pid: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def _wait(process: subprocess.Popen[bytes], output: int, errors: int) -> None:
    deadline = time.monotonic() + TIMEOUT_S
    while process.poll() is None:
        if time.monotonic() >= deadline:
            raise BridgeError(504, "OpenCode exceeded its 75-second deadline")
        if os.fstat(output).st_size + os.fstat(errors).st_size > MAX_OUTPUT_BYTES:
            raise BridgeError(502, "OpenCode exceeded the response-size limit")
        time.sleep(POLL_S)
    if os.fstat(output).st_size + os.fstat(errors).st_size > MAX_OUTPUT_BYTES:
        raise BridgeError(502, "OpenCode exceeded the response-size limit")


def parse_events(raw: str, returncode: int | None) -> dict[str, Any]:
    """Accept only a zero-cost text completion; never accept tool-call results."""
    try:
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (ValueError, TypeError) as exc:
        raise BridgeError(502, "OpenCode returned invalid event JSON") from exc
    text: list[str] = []
    finish: dict[str, Any] | None = None
    for event in events:
        part = _event_part(event)
        if event.get("type") == "text":
            if not isinstance(part.get("text"), str):
                raise BridgeError(502, "OpenCode returned invalid text")
            text.append(part["text"])
        if event.get("type") == "step_finish":
            finish = part
    if returncode != 0 or not finish or finish.get("reason") != "stop" or not text:
        raise BridgeError(502, "OpenCode did not finish a text response")
    if finish.get("cost") != 0:
        raise BridgeError(502, "OpenCode did not report a free completion")
    return _completion("\n".join(text), finish.get("tokens") or {})


def _event_part(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise BridgeError(502, "OpenCode returned an invalid event")
    if event.get("type") == "error":
        _raise_upstream(event)
    part = event.get("part", {})
    if not isinstance(part, dict):
        raise BridgeError(502, "OpenCode returned an invalid event part")
    if event.get("type") == "tool_use" or part.get("type") == "tool":
        raise BridgeError(502, "OpenCode requested a tool; Sentinel accepts text only")
    return part


def _raise_upstream(event: dict[str, Any]) -> None:
    data = (event.get("error") or {}).get("data") or {}
    status = data.get("statusCode")
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = 502
    # Upstream messages may contain prompt text; expose only a controlled label.
    raise BridgeError(status, f"OpenCode model request failed (HTTP {status})")


def _completion(text: str, tokens: dict[str, Any]) -> dict[str, Any]:
    cached = tokens.get("cache") or {}
    return {
        "model": MODEL,
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": int(tokens.get("input", 0)) + int(cached.get("read", 0)),
            "completion_tokens": int(tokens.get("output", 0)) + int(tokens.get("reasoning", 0)),
        },
    }
