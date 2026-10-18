"""Materialize one invented review example and optionally check its truth in Docker.

The corpus keeps expected results and held-out tests outside the reviewed repository.
This helper runs Git locally, but all example code/tests execute through Sentinel's
configured Docker sandbox. It makes no AI requests; use Sentinel's normal CLI next.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sentinel.bootstrap import build_sandbox
from sentinel.core.configuration.config import load_settings
from sentinel.core.domain.ports import SandboxRunner

CASES = Path(__file__).resolve().parents[1] / "evals/review_quality/cases"


class QualityCase(BaseModel):
    """Declared contract and test commands for one authored example."""

    model_config = ConfigDict(extra="forbid")
    name: str
    language: Literal["python", "javascript", "typescript"]
    expected_bug: bool
    source: str
    contract: str
    test_command: list[str]
    oracle_command: list[str]


def copy_text_tree(source: Path, destination: Path) -> None:
    """Copy authored text fixtures with fresh timestamps and portable shell newlines."""
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("quality fixtures must not contain symlinks")
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")


def run_git(root: Path, *arguments: str) -> str:
    """Create fixture history without hooks, signing prompts or personal author data."""
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Sentinel quality example",
        "GIT_AUTHOR_EMAIL": "example@example.invalid",
        "GIT_COMMITTER_NAME": "Sentinel quality example",
        "GIT_COMMITTER_EMAIL": "example@example.invalid",
    }
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def check_holdout(sandbox: SandboxRunner, root: Path, fixture: Path, case: QualityCase) -> bool:
    """Run independent behaviour tests on a throwaway copy, never in model context."""
    with tempfile.TemporaryDirectory(prefix="sentinel-quality-check-") as temporary:
        scratch = Path(temporary)
        shutil.copytree(
            root,
            scratch,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", ".test-build", "__pycache__"),
        )
        copy_text_tree(fixture / "oracle", scratch)
        return sandbox.run(scratch, case.oracle_command).ok


def prepare_case(name: str, destination: Path, *, check: bool = False) -> dict[str, object]:
    """Create an exclusive Git repo; verify safe/broken contracts when requested."""
    known = {path.name for path in CASES.iterdir() if path.is_dir()}
    if name not in known:
        raise ValueError(f"unknown quality case: {name}")
    fixture = CASES / name
    case = QualityCase.model_validate_json((fixture / "case.json").read_text())
    sandbox = build_sandbox(load_settings()) if check else None
    if check and (sandbox is None or sandbox.isolation != "docker" or not sandbox.is_available()):
        raise ValueError("--check requires the configured Docker sandbox")
    destination.mkdir(parents=True, exist_ok=False)
    copy_text_tree(fixture / "base", destination)
    run_git(destination, "init", "-q")
    run_git(destination, "add", ".")
    run_git(destination, "commit", "-qm", "baseline")
    if sandbox is not None and not check_holdout(sandbox, destination, fixture, case):
        raise ValueError("safe baseline failed the independent check")
    copy_text_tree(fixture / "change", destination)
    # Force content hashing: copying a same-size file can preserve enough timestamp
    # metadata for Git's stat cache to miss a change on a fast filesystem.
    run_git(destination, "add", "--renormalize", ".")
    if not run_git(destination, "diff", "--cached", "--name-only").strip():
        raise ValueError("the example has no staged change; do not count it as a review")
    if sandbox is not None:
        normal = sandbox.run(destination, case.test_command)
        behaviour = check_holdout(sandbox, destination, fixture, case)
        if not normal.ok or behaviour == case.expected_bug:
            raise ValueError("example tests do not match the declared contract")
    return {"repository": str(destination), "language": case.language, "checks_run": check}


def main() -> None:
    """Prepare one case; calling a real provider remains an explicit separate command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    print(
        json.dumps(prepare_case(options.case, options.destination.resolve(), check=options.check))
    )


if __name__ == "__main__":
    main()
