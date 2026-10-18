"""Reject unsafe/unfinished CLI envelopes before Sentinel sees a completion."""

from __future__ import annotations

import io
import json
import tempfile
from unittest.mock import Mock

import pytest
from tools.opencode_bridge.runner import BridgeError, _wait, parse_events
from tools.opencode_bridge.server import Handler


def events(*items: dict[str, object]) -> str:
    return "\n".join(json.dumps(item) for item in items)


def finish(**changes: object) -> dict[str, object]:
    part = {
        "reason": "stop",
        "cost": 0,
        "tokens": {
            "input": 10,
            "output": 5,
            "reasoning": 2,
            "cache": {"read": 20},
        },
    }
    return {"type": "step_finish", "part": {**part, **changes}}


TEXT = {"type": "text", "part": {"type": "text", "text": '{"findings": []}'}}


def test_success_counts_cached_input_and_reasoning_in_existing_usage_fields() -> None:
    response = parse_events(events(TEXT, finish()), 0)
    assert response["usage"] == {"prompt_tokens": 30, "completion_tokens": 7}
    assert response["choices"][0]["message"]["content"] == '{"findings": []}'


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("not json", 0),
        ("[]", 0),
        (events(TEXT), 0),
        (events(TEXT, finish()), 1),
        (events(TEXT, finish(cost=0.01)), 0),
        (events(TEXT, finish(reason="length")), 0),
        (events({"type": "tool_use", "part": {"type": "tool"}}, TEXT, finish()), 0),
        (events({"type": "text", "part": []}), 0),
    ],
)
def test_incomplete_nonfree_and_tool_responses_are_rejected(raw: str, code: int) -> None:
    with pytest.raises(BridgeError):
        parse_events(raw, code)


def test_upstream_error_retains_status_without_echoing_provider_data() -> None:
    with pytest.raises(BridgeError) as caught:
        parse_events(
            events(
                {
                    "type": "error",
                    "error": {
                        "data": {
                            "statusCode": 429,
                            "message": "private-source-key",
                        }
                    },
                }
            ),
            1,
        )
    assert caught.value.status == 429
    assert "private-source-key" not in str(caught.value)


def test_runner_checks_deadline_and_response_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 100.0])
    monkeypatch.setattr("tools.opencode_bridge.runner.time.monotonic", lambda: next(clock))
    process = Mock()
    process.poll.return_value = None
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        with pytest.raises(BridgeError, match="deadline"):
            _wait(process, output.fileno(), errors.fileno())
        process.poll.return_value = 0
        output.write(b"x" * 1_048_577)
        output.flush()
        monkeypatch.setattr("tools.opencode_bridge.runner.time.monotonic", lambda: 0.0)
        with pytest.raises(BridgeError, match="size limit"):
            _wait(process, output.fileno(), errors.fileno())


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "deepseek-v4.1-flash"},
        {"max_tokens": 1000000},
        {"max_tokens": True},
        {"temperature": float("nan")},
        {"temperature": 2},
        {"command": "run this"},
    ],
)
def test_bridge_rejects_paid_models_unbounded_options_and_general_commands(
    changes: dict[str, object],
) -> None:
    body = {
        "model": "deepseek-v4.1-flash-free",
        "prompt": "synthetic",
        "max_tokens": 4096,
        "temperature": 0.1,
        **changes,
    }
    raw = json.dumps(body).encode()
    handler = Mock()
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    with pytest.raises(BridgeError):
        Handler.read_prompt(handler)


def test_unauthenticated_request_never_reads_prompt_or_starts_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_OPENCODE_TOKEN", "private-local-token")
    handler = Mock()
    handler.headers = {}
    Handler.do_POST(handler)
    assert handler.reply.call_args.args[0] == 401
    handler.read_prompt.assert_not_called()
