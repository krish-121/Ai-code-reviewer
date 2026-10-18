"""Scratch stdin transfer must not follow links, expose secrets or trust tar metadata."""

import io
import os
import tarfile
from pathlib import Path

import pytest

from sentinel.core.paths import RepositoryPathError
from sentinel.sandbox import workspace
from sentinel.sandbox.runners import DockerSandbox
from sentinel.sandbox.workspace import SandboxWorkspaceError, pack_workspace, unpack_workspace


def test_copy_command_never_mounts_worker_paths_or_credentials(tmp_path: Path) -> None:
    sandbox = DockerSandbox(transport="copy")
    cmd = sandbox.command(tmp_path, ["python", "-m", "pytest"], "sbx", network=False)
    assert str(tmp_path) not in " ".join(cmd)
    assert "-v" not in cmd and "--mount" not in cmd
    assert "--network none" in " ".join(cmd)
    assert "--read-only" in cmd and "--cap-drop ALL" in " ".join(cmd)
    assert "--security-opt no-new-privileges" in " ".join(cmd)
    assert "sentinel.sandbox.launch" in cmd and "-i" in cmd
    assert "docker.sock" not in " ".join(cmd)


def test_roundtrip_preserves_content_but_omits_secrets_and_dependencies(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "safe.py").write_bytes(b"print('safe')\n")
    (source / "safe.py").chmod(0o700)
    (source / "empty").mkdir()
    (source / ".env").write_text("SECRET=never")
    (source / "node_modules").mkdir()
    (source / "node_modules/unsafe.js").write_text("never")
    archive = io.BytesIO()
    pack_workspace(source, archive)
    archive.seek(0)
    unpack_workspace(archive, dest)
    assert (dest / "safe.py").read_bytes() == b"print('safe')\n"
    assert os.stat(dest / "safe.py").st_mode & 0o777 == 0o700
    assert sorted(path.name for path in dest.iterdir()) == ["empty", "safe.py"]
    assert (dest / "empty").is_dir()


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_packing_refuses_linked_files(tmp_path: Path, link: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("must not transfer")
    if link == "symlink":
        (source / "escape").symlink_to(outside)
    else:
        os.link(outside, source / "escape")
    with pytest.raises((RepositoryPathError, OSError)):
        pack_workspace(source, io.BytesIO())


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("../escape", tarfile.REGTYPE),
        ("/escape", tarfile.REGTYPE),
        ("escape", tarfile.SYMTYPE),
        ("escape", tarfile.LNKTYPE),
        ("escape", tarfile.FIFOTYPE),
    ],
)
def test_unpacking_rejects_traversal_and_special_entries(
    tmp_path: Path, name: str, kind: bytes
) -> None:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
        archive.addfile(member)
    data.seek(0)
    with pytest.raises((RepositoryPathError, SandboxWorkspaceError)):
        unpack_workspace(data, tmp_path)
    assert not (tmp_path / "escape").exists()


def test_transfer_budgets_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "large").write_bytes(b"x" * 10)
    monkeypatch.setattr(workspace, "MAX_WORKSPACE_BYTES", 5)
    with pytest.raises(SandboxWorkspaceError, match="budget"):
        pack_workspace(tmp_path, io.BytesIO())
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("large")
        member.size = 10
        archive.addfile(member, io.BytesIO(b"x" * 10))
    data.seek(0)
    with pytest.raises(SandboxWorkspaceError, match="budget"):
        unpack_workspace(data, tmp_path)
    monkeypatch.setattr(workspace, "MAX_WORKSPACE_BYTES", 100)
    monkeypatch.setattr(workspace, "MAX_WORKSPACE_FILES", 0)
    with pytest.raises(SandboxWorkspaceError, match="budget"):
        pack_workspace(tmp_path, io.BytesIO())
