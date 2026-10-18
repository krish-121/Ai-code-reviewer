"""Installed Docker entry point: load scratch stdin, then launch the test.

DockerSandbox uses isolated Python mode so a repository cannot shadow this module.
Stdin becomes /dev/null before execution; the tar contains no worker credentials.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sentinel.sandbox.workspace import SandboxWorkspaceError, unpack_workspace


def main() -> None:
    """Load the bounded scratch archive and execute an argument list without a shell."""
    command = json.loads(sys.argv[1])
    if not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command):
        raise SandboxWorkspaceError("expected a non-empty command argument list")
    unpack_workspace(sys.stdin.buffer, Path.cwd())
    with open(os.devnull, "rb") as closed_input:
        os.dup2(closed_input.fileno(), sys.stdin.fileno())
    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
