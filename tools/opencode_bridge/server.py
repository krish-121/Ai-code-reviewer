"""An authenticated, single-purpose local HTTP bridge to official OpenCode.

Sentinel's provider posts a prompt here. This standalone service uses only Python's
standard library so its Docker image contains no Sentinel repository or API keys.
It exposes no general OpenCode file, shell, configuration or authentication APIs.
"""

from __future__ import annotations

import hmac
import json
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .runner import MODEL, BridgeError, run_opencode

MAX_INPUT_BYTES = 1_048_576
SLOT = threading.BoundedSemaphore(1)


class Handler(BaseHTTPRequestHandler):
    """Serve health and authenticated completions; log no prompts or tokens."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP access logs, including untrusted URL text."""

    def do_GET(self) -> None:
        """Return a non-secret health response for Docker and the setup helper."""
        if self.path != "/health":
            self.reply(404, {"error": {"message": "Not found"}})
            return
        self.reply(200, {"ok": True, "model": MODEL})

    def do_POST(self) -> None:
        """Authenticate before reading a bounded body and serialize model calls."""
        token = os.environ["SENTINEL_OPENCODE_TOKEN"]
        if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
            self.reply(401, {"error": {"message": "Local bridge token required"}})
            return
        if self.path != "/complete":
            self.reply(404, {"error": {"message": "Not found"}})
            return
        if not SLOT.acquire(blocking=False):
            self.reply(503, {"error": {"message": "Local bridge busy; try again later"}})
            return
        try:
            self.connection.settimeout(10)
            prompt, max_tokens, temperature = self.read_prompt()
            result = run_opencode(prompt, max_tokens, temperature)
            self.reply(200, result)
        except BridgeError as exc:
            self.reply(exc.status, {"error": {"message": str(exc)}})
        except (OSError, ValueError, KeyError, TypeError):
            self.reply(502, {"error": {"message": "Local bridge could not finish the request"}})
        finally:
            SLOT.release()

    def read_prompt(self) -> tuple[str, int, float]:
        """Validate the minimal API: one fixed free model and a nonempty prompt."""
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_INPUT_BYTES:
            raise BridgeError(413, "Prompt exceeds the request-size limit")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict) or set(body) != {
            "model",
            "prompt",
            "max_tokens",
            "temperature",
        }:
            raise BridgeError(400, "Expected model, prompt, max_tokens and temperature only")
        if body["model"] != MODEL:
            raise BridgeError(400, "Only the approved free DeepSeek model is available")
        prompt = body["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise BridgeError(400, "Prompt must be nonempty text")
        max_tokens, temperature = _sampling(body)
        return prompt, max_tokens, temperature

    def reply(self, status: int, body: dict[str, Any]) -> None:
        """Return JSON and close the connection, including on an unread bad body."""
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)


def _sampling(body: dict[str, Any]) -> tuple[int, float]:
    limit, temperature = body["max_tokens"], body["temperature"]
    if type(limit) is not int or not 256 <= limit <= 4096:
        raise BridgeError(400, "max_tokens must be between 256 and 4096")
    if not isinstance(temperature, int | float) or not math.isfinite(temperature):
        raise BridgeError(400, "temperature must be a finite number")
    if not 0 <= temperature <= 1:
        raise BridgeError(400, "temperature must be between zero and one")
    return limit, float(temperature)


def main() -> None:
    """Require a separate local token; listen only inside the container."""
    if len(os.environ.get("SENTINEL_OPENCODE_TOKEN", "")) < 32:
        raise SystemExit("Set a local bridge token of at least 32 characters")
    ThreadingHTTPServer(("0.0.0.0", 4097), Handler).serve_forever()  # noqa: S104 - Docker binds loopback


if __name__ == "__main__":
    main()
