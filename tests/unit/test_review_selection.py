"""Review inputs must identify one real source, without silently discarding options."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sentinel.analysis.diff.git import GitError, path_changeset
from sentinel.apps.cli.main import app


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--staged", "--worktree"], "choose only one review source"),
        (["--range", "main..HEAD", "--staged"], "choose only one review source"),
        ([".", "--staged"], "choose only one review source"),
        (["--path", ".", "--pr", "1"], "choose only one review source"),
        ([".", "--path", "."], "choose only one review source"),
        (["--pr", "1", "--worktree"], "choose only one review source"),
        (["--repo", "acme/example", "--staged"], "--repo requires --pr"),
        (["--pr", "0"], "x>=1"),
        (["missing-sentinel-directory"], "does not exist"),
        (["--path", "missing-sentinel-directory"], "does not exist"),
    ],
)
def test_invalid_selection_fails_before_settings_database_or_ai(
    arguments: list[str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid_settings(**kwargs: object) -> None:
        pytest.fail("invalid inputs must not load private settings or begin a review")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sentinel.apps.cli.review_commands.load_cli_settings", forbid_settings)
    result = CliRunner().invoke(app, ["review", *arguments])
    assert result.exit_code == 2, result.output
    assert message in " ".join(result.output.replace("│", " ").split())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("git_repository", [False, True])
def test_missing_subpath_is_an_error_not_an_empty_clean_review(
    tmp_path: Path, git_repository: bool
) -> None:
    if git_repository:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(GitError, match="review path does not exist"):
        path_changeset(tmp_path, tmp_path / "misspelled")


def test_missing_root_is_an_error_but_an_existing_empty_directory_is_valid(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="review path does not exist"):
        path_changeset(tmp_path / "missing")
    assert not path_changeset(tmp_path).files


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/acme/reviewer.git", "acme/reviewer"),
        ("https://github.com/acme/reviewer.demo.git", "acme/reviewer.demo"),
        ("git@github.com:acme/reviewer.demo.git", "acme/reviewer.demo"),
        ("ssh://git@github.com/acme/reviewer.demo.git", "acme/reviewer.demo"),
        ("https://github.com/acme/reviewer.demo", "acme/reviewer.demo"),
        ("https://github.com/acme/reviewer.git.git", "acme/reviewer.git"),
        ("https://gitlab.com/acme/reviewer.demo.git", None),
    ],
)
def test_cli_infers_github_repository_names_with_dots(
    remote: str, expected: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sentinel.apps.cli.review_commands import _origin_repo

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=0, stdout=remote),
    )
    assert _origin_repo() == expected
