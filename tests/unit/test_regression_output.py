"""Regression evidence distinguishes real Node assertions from failed test loading."""

from pathlib import Path

import pytest

from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ports import SandboxResult
from sentinel.core.fixes.regression import check_regression_tests
from sentinel.core.fixes.scratch import scratch_copy
from tests.unit.test_fix_engine import FakeSandbox, ok

NODE_ASSERTION = """TAP version 13
# Subtest: binds user input
not ok 1 - binds user input
  ---
  type: 'test'
  failureType: 'testCodeFailure'
  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  ...
1..1
# tests 1
# pass 0
# fail 1
# cancelled 0
"""
NODE_LOAD_ERROR = """TAP version 13
# Error: Cannot find module '../missing'
not ok 1 - tests/query.test.js
  ---
  type: 'test'
  failureType: 'testCodeFailure'
  code: 'ERR_TEST_FAILURE'
  ...
# tests 1
# fail 1
# cancelled 0
"""


NODE_RUNTIME_ERROR = """TAP version 13
# Subtest: missing user returns fallback
not ok 1 - missing user returns fallback
  ---
  type: 'test'
  failureType: 'testCodeFailure'
  code: 'ERR_TEST_FAILURE'
  name: 'TypeError'
  stack: |-
    Object.userName (/workspace/example.js:4:10)
    TestContext.<anonymous> (/workspace/tests/user.test.js:5:20)
  ...
# tests 1
# fail 1
# cancelled 0
"""


@pytest.mark.parametrize(
    ("output", "accepted"),
    [
        ("1 failed", True),
        ("assertion compared a message containing 1 error\n1 failed in 0.1s", True),
        ("1 failed, 1 error", False),
        (NODE_ASSERTION, True),
        (NODE_RUNTIME_ERROR, True),
        (NODE_RUNTIME_ERROR + NODE_LOAD_ERROR, False),
        (NODE_LOAD_ERROR, False),
        (NODE_LOAD_ERROR + "# logged: 1 failed\n", False),
        (NODE_ASSERTION + NODE_LOAD_ERROR, False),
        (NODE_ASSERTION.replace("# cancelled 0", "# cancelled 1"), False),
        (NODE_ASSERTION.replace("# fail 1", "# fail 0"), False),
        (NODE_ASSERTION.replace("TAP version 13", "custom reporter"), False),
        (NODE_ASSERTION.replace("  code: 'ERR_ASSERTION'", "  # code: 'ERR_ASSERTION'"), False),
    ],
)
def test_regression_requires_completed_assertion_failure(
    tmp_path: Path, output: str, accepted: bool
) -> None:
    config = RepoConfig()
    config.fix.regression_command = ["node", "--test", "{files}"]
    sandbox = FakeSandbox(ok(1, output), ok())
    result = check_regression_tests(
        sandbox, tmp_path, tmp_path, {"test.js": ""}, config, scratch_copy
    )
    assert (result.status == "passed") is accepted
    assert len(sandbox.commands) == (2 if accepted else 1)


@pytest.mark.parametrize(("timed_out", "exit_code"), [(True, 1), (False, 2), (False, 124)])
def test_node_failure_exit_and_deadline_are_required(
    tmp_path: Path, timed_out: bool, exit_code: int
) -> None:
    config = RepoConfig()
    config.fix.regression_command = ["node", "--test", "{files}"]
    before = SandboxResult([], exit_code, NODE_ASSERTION, "", 5, timed_out=timed_out)
    sandbox = FakeSandbox(before)
    result = check_regression_tests(
        sandbox, tmp_path, tmp_path, {"test.js": ""}, config, scratch_copy
    )
    assert result.status == "failed"
