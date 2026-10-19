#!/usr/bin/env python3
"""Create the Sentinel demo repository as a real git repo with two branches.

    python demo/build_demo_repo.py /tmp/sentinel-demo
    cd /tmp/sentinel-demo
    sentinel review --range main..feature/search-and-reports

``main`` holds a clean little shop backend. ``feature/search-and-reports`` adds features
with deliberately planted problems: SQL injection (Python and TypeScript), an
authorization check that trusts a request header before authenticating, an N+1 query,
an O(n^2) de-duplication, blocking calls and an un-awaited coroutine in async code, a
swallowed exception, unhandled JSON parsing, untested new code, a committed secret and
.env file, and a prompt-injection comment aimed at AI reviewers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "sentinel-demo-repo"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Demo Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Demo Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}


def git(repo: Path, *args: str) -> None:
    # Demo commits must not need the visitor's signing key or execute their hooks.
    subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                    "-c", "commit.gpgSign=false", "-C", str(repo), *args], check=True, env=ENV,
                   stdout=subprocess.DEVNULL)  # noqa: S603


def overlay(src: Path, dest: Path) -> None:
    for item in src.rglob("*"):
        if item.is_file():
            target = dest / item.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def build(target: Path) -> Path:
    # Exclusive creation also refuses symlinks and closes the exists/delete race.
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Refusing to replace existing destination: {target}")
    target.mkdir(parents=True)
    git(target, "init", "-q", "-b", "main")
    overlay(HERE / "base", target)
    git(target, "add", "-A")
    git(target, "commit", "-qm", "Initial shop API")
    git(target, "checkout", "-q", "-b", "feature/search-and-reports")
    overlay(HERE / "feature", target)
    git(target, "add", "-A", "-f")
    git(target, "commit", "-qm", "Add search, reports, notifications and admin export")
    return target


if __name__ == "__main__":
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "sentinel-demo").resolve()
    build(dest)
    print(f"Demo repository created at {dest}")
    print(f"  cd {dest} && sentinel review --range main..feature/search-and-reports")
