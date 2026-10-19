"""The public demo must be isolated, honestly labelled and reproducible through real gates."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel.apps.api.app import create_app
from sentinel.core.configuration.config import Settings
from tests.integration.test_sandbox import DOCKER, HAS_DOCKER

ROOT = Path(__file__).resolve().parents[2]


def test_demo_ignores_saved_settings_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("demo_support")
    monkeypatch.setenv("SENTINEL_PROVIDER", "gemini")
    monkeypatch.setenv("SENTINEL_GEMINI_KEY", "invented-do-not-use")
    monkeypatch.setenv("SENTINEL_AUTH_MODE", "token")
    monkeypatch.setenv("SENTINEL_LOCAL_ROOTS", "/")
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "sqlite:///unrelated.db")
    settings = module.demo_settings(tmp_path / "demo.db", tmp_path / "sample")
    assert isinstance(settings, Settings)
    assert settings.provider == "none" and settings.gemini_api_key is None
    assert settings.github_token is None and settings.github_private_key_path is None
    assert settings.auth_mode == "local" and settings.allowed_roots() == [
        (tmp_path / "sample").resolve()
    ]
    assert settings.database_url == f"sqlite:///{tmp_path / 'demo.db'}"
    assert settings.sandbox_transport == "copy" and not settings.allow_process_sandbox


def test_demo_refuses_to_replace_existing_data(tmp_path: Path) -> None:
    database = tmp_path / "precious.db"
    database.write_bytes(b"keep this file")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/seed_demo.py"),
            "--review-only",
            "--db",
            str(database),
            "--repo",
            str(tmp_path / "new-sample"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "already exist" in result.stderr
    assert database.read_bytes() == b"keep this file" and not (tmp_path / "new-sample").exists()


@pytest.mark.docker
@pytest.mark.skipif(not HAS_DOCKER, reason="Docker daemon or sandbox image unavailable")
def test_public_demo_entrypoint_validates_then_normal_api_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = tmp_path / "sample", tmp_path / "demo.db"
    env = {
        **os.environ,
        "SENTINEL_PROVIDER": "gemini",
        "SENTINEL_GEMINI_KEY": "invented-invalid-key",
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/seed_demo.py"),
            "--repo",
            str(root),
            "--db",
            str(database),
            "--image",
            DOCKER.image,
            "--transport",
            DOCKER.transport,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads(database.with_suffix(".receipt.json").read_text())
    assert receipt["complete"] and not receipt["auto_applied"]
    assert {"bug", "security", "performance", "tests"}.issubset(receipt["categories"])
    assert "SQL injection in find_user" in receipt["rejected"]
    assert receipt["fix"]["provider"] == "replay" and receipt["fix"]["model"] == "scripted-demo"
    assert len(receipt["fix"]["checks"]) == 7
    assert all(check["status"] == "passed" for check in receipt["fix"]["checks"])
    assert "LIKE '%{term}%'" in (root / "app/db.py").read_text()
    assert not (root / "tests/test_db_regression.py").exists()

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("demo_support")
    settings = module.demo_settings(database, root, transport=DOCKER.transport, image=DOCKER.image)
    db, reviews, fixes = module.demo_services(settings)
    with TestClient(create_app(settings, db=db, reviews=reviews, fixes=fixes)) as client:
        headers = {"X-Sentinel-Client": "public-demo-test"}
        blocked = client.post(
            "/api/reviews", json={"path": str(tmp_path), "mode": "path"}, headers=headers
        )
        assert blocked.status_code == 403
        applied = client.post(f"/api/fixes/{receipt['fix_id']}/apply", headers=headers)
        assert applied.status_code == 200
        assert set(applied.json()["applied"]) == {"app/db.py", "tests/test_db_regression.py"}
        assert client.get(f"/api/fixes/{receipt['fix_id']}").json()["status"] == "applied"
    tested = DOCKER.run(root, ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"])
    assert tested.ok and "6 passed" in tested.stdout


def test_demo_server_refuses_an_unmarked_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    server = importlib.import_module("serve_demo")
    database, repository = tmp_path / "private.db", tmp_path / "sample"
    database.write_bytes(b"keep this unrelated database")
    (repository / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        sys, "argv", ["serve_demo.py", "--db", str(database), "--repo", str(repository)]
    )
    with pytest.raises(SystemExit) as error:
        server.main()
    assert error.value.code == 2
    assert database.read_bytes() == b"keep this unrelated database"
