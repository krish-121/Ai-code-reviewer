"""Drain child pipes with a shared byte cap and kill the process group on overflow."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress

MAX_CAPTURE_BYTES = 40_000


def communicate_capped(
    proc: subprocess.Popen[bytes],
    timeout_s: float,
    cleanup: Callable[[], None] | None = None,
    *,
    max_bytes: int = MAX_CAPTURE_BYTES,
) -> tuple[str, str, bool]:
    """Bound memory while reading; never buffer unlimited output before truncating."""
    outputs = [bytearray(), bytearray()]
    deadline = time.monotonic() + timeout_s
    with selectors.DefaultSelector() as selector:
        for index, pipe in enumerate((proc.stdout, proc.stderr)):
            if pipe is not None:
                selector.register(pipe, selectors.EVENT_READ, index)
        timed_out, overflow = _drain(selector, outputs, deadline, max_bytes)
    if timed_out or overflow:
        _kill_group(proc)
        if cleanup is not None:
            cleanup()
    try:
        proc.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        if cleanup is not None:
            cleanup()
        proc.wait(timeout=5)
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()
    out, err = [part.decode("utf-8", errors="replace") for part in outputs]
    if overflow:
        proc.returncode = -1
        err += "\noutput limit exceeded; process terminated"
    return out, err, timed_out


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _drain(
    selector: selectors.BaseSelector, outputs: list[bytearray], deadline: float, max_bytes: int
) -> tuple[bool, bool]:
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True, False
        for key, _ in selector.select(min(remaining, 0.1)):
            chunk = os.read(key.fd, 4096)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            room = max_bytes - sum(map(len, outputs))
            outputs[key.data].extend(chunk[:room])
            if len(chunk) > room:
                return False, True
    return False, False
