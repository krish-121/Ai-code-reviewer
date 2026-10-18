"""The public quality corpus stages real changes without leaking its answer key."""

from pathlib import Path

import pytest
from scripts.prepare_quality_case import CASES, QualityCase, copy_text_tree, prepare_case, run_git

NAMES = sorted(path.name for path in CASES.iterdir() if path.is_dir())


@pytest.mark.parametrize("name", NAMES)
def test_example_has_real_staged_source_and_withholds_oracle(tmp_path: Path, name: str) -> None:
    root = tmp_path / "case-01"
    metadata = QualityCase.model_validate_json((CASES / name / "case.json").read_text())
    prepare_case(name, root)
    assert run_git(root, "diff", "--cached", "--name-only").strip() == metadata.source
    assert run_git(root, "show", ":" + metadata.source) == (root / metadata.source).read_text()
    assert not (root / "case.json").exists()
    assert not list(root.rglob("*holdout*"))
    assert run_git(root, "log", "-1", "--format=%ae").strip() == "example@example.invalid"


def test_unknown_and_existing_destinations_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "my-project"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("user data")
    with pytest.raises(ValueError, match="unknown quality case"):
        prepare_case("../outside", root)
    with pytest.raises(FileExistsError):
        prepare_case(NAMES[0], root)
    assert marker.read_text() == "user data"
    assert not (root / ".git").exists()


def test_shell_fixture_copy_uses_lf_even_on_windows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.sh").write_bytes(b"#!/bin/sh\r\nexit 0\r\n")
    copy_text_tree(source, tmp_path / "destination")
    assert (tmp_path / "destination/test.sh").read_bytes() == b"#!/bin/sh\nexit 0\n"
