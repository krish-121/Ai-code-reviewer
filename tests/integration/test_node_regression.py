"""Actual Node TAP assertions can validate a regression; failed module loads cannot."""

import os
from pathlib import Path

import pytest

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.fixes.regression import check_regression_tests
from sentinel.core.fixes.scratch import scratch_copy
from sentinel.sandbox.runners import DockerSandbox


@pytest.mark.docker
@pytest.mark.parametrize("failure", ["assertion", "load", "runtime"])
def test_real_node_regression_evidence(tmp_path: Path, failure: str) -> None:
    sandbox = DockerSandbox(
        image=os.environ.get("SENTINEL_TEST_SANDBOX_IMAGE", "sentinel-sandbox:latest"),
        transport="copy" if os.environ.get("SENTINEL_TEST_DOCKER_COPY") == "1" else "bind",
    )
    if not sandbox.is_available():
        pytest.skip("docker daemon or sentinel-sandbox image unavailable")
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    original = "exports.query = () => 'unsafe';\n"
    if failure == "runtime":
        original = "exports.query = () => { throw new TypeError('missing value'); };\n"
    (before / "query.js").write_text(original)
    (after / "query.js").write_text("exports.query = () => 'safe';\n")
    module = "./missing.js" if failure == "load" else "./query.js"
    test = (
        "const { test } = require('node:test');\n"
        "const assert = require('node:assert/strict');\n"
        f"const {{ query }} = require('{module}');\n"
        "test('query is safe', () => assert.equal(query(), 'safe'));\n"
    )
    (after / "query.test.js").write_text(test)
    config = RepoConfig()
    config.fix.regression_command = ["node", "--test", "{files}"]
    outcome = check_regression_tests(
        sandbox, before, after, {"query.test.js": test}, config, scratch_copy
    )
    assert outcome.status == ("failed" if failure == "load" else "passed"), outcome.detail
