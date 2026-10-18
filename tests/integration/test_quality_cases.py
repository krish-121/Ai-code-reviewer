"""Offline Docker checks keep each published example's expected behaviour honest."""

import os
from pathlib import Path

import pytest
from scripts import prepare_quality_case as examples

from sentinel.core.configuration.config import Settings

NAMES = sorted(path.name for path in examples.CASES.iterdir() if path.is_dir())


@pytest.mark.docker
@pytest.mark.parametrize("name", NAMES)
def test_quality_case_contract_in_real_docker(
    tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        sandbox_image=os.environ.get("SENTINEL_TEST_SANDBOX_IMAGE", "sentinel-sandbox:latest"),
        sandbox_transport="copy" if os.environ.get("SENTINEL_TEST_DOCKER_COPY") == "1" else "bind",
    )
    sandbox = examples.build_sandbox(settings)
    if sandbox is None or not sandbox.is_available():
        pytest.skip("docker daemon or sentinel-sandbox image unavailable")
    monkeypatch.setattr(examples, "load_settings", lambda: settings)
    result = examples.prepare_case(name, tmp_path / "case-01", check=True)
    assert result["checks_run"] is True
