"""HTTP-backed free fallback: ordering, cost boundaries, cooldown and visible provenance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from sentinel.ai.providers.base import _retry_after_seconds
from sentinel.ai.providers.factory import create_provider
from sentinel.ai.providers.fallback import FallbackProvider
from sentinel.ai.providers.http_providers import GeminiProvider
from sentinel.ai.providers.opencode import FREE_MODELS, OpenCodeFreeProvider
from sentinel.core.configuration.config import load_settings, save_user_setting
from sentinel.core.domain.ai import FixRequest
from sentinel.core.domain.models import Category
from sentinel.core.domain.ports import AIBlockedError, AIConfigurationError, AIError
from sentinel.infrastructure.storage.cache import MemoryCache
from tests.unit.test_ai_providers import FIX, GOOD, Script, gemini_body, ok, request


def chat_body(payload: Any) -> dict[str, Any]:
    return {
        "model": FREE_MODELS[0],
        "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }


def chain(script: Script, *, cache: MemoryCache | None = None) -> FallbackProvider:
    settings = load_settings(
        Path("/nonexistent-fallback-config.toml"),
        env={
            "SENTINEL_PROVIDER": "gemini",
            "GEMINI_API_KEY": "secret-key",
            "SENTINEL_OPENCODE_TOKEN": "local-bridge-token",
            "SENTINEL_FREE_FALLBACK": "true",
            "SENTINEL_FALLBACK_COOLDOWN": "300",
            "SENTINEL_MODEL": "gemini-3.8-flash",
        },
    )
    provider = create_provider(
        settings, transport=script.transport, cache=cache or MemoryCache(), sleep=lambda _: None
    )
    assert isinstance(provider, FallbackProvider)
    return provider


def rate_limited() -> httpx.Response:
    return httpx.Response(
        429, json={"error": {"message": "quota reached"}}, headers={"retry-after": "900"}
    )


def test_primary_success_makes_no_fallback_calls() -> None:
    script = Script(ok(gemini_body(json.dumps(GOOD))))
    provider = chain(script)
    result = provider.review(request())
    assert result.provider == "gemini" and result.fallback_events == []
    assert len(script.requests) == 1
    provider.close()
    assert all(p.client.is_closed for p in provider.providers)


def test_quota_switches_to_deepseek_without_forwarding_gemini_key() -> None:
    script = Script(rate_limited(), ok(chat_body(GOOD)))
    result = chain(script).review(request())
    assert result.provider == "opencode" and result.model == FREE_MODELS[0]
    assert "rate limit reached" in result.fallback_events[0]
    assert result.usage.input_tokens == 12
    outgoing = script.requests[-1]
    assert outgoing.url.host == "127.0.0.1"
    assert outgoing.url.path == "/complete"
    assert outgoing.headers["authorization"] == "Bearer local-bridge-token"
    assert "x-goog-api-key" not in outgoing.headers
    assert "secret-key" not in outgoing.content.decode()
    body = script.body(1)
    assert body["model"] == FREE_MODELS[0]
    assert "JSON Schema" in body["prompt"]


def test_deepseek_outage_is_reported_without_trying_unverified_glm() -> None:
    script = Script(rate_limited(), httpx.Response(503))
    with pytest.raises(AIError, match="503"):
        chain(script).review(request())
    assert len(script.requests) == 2


def test_cooldown_survives_provider_recreation_and_respects_retry_after() -> None:
    cache = MemoryCache()
    first = chain(Script(rate_limited(), ok(chat_body(GOOD))), cache=cache)
    first.clock = lambda: 1_000.0
    first.review(request())
    second_script = Script(ok(chat_body(GOOD)), ok(gemini_body(json.dumps(GOOD))))
    second = chain(second_script, cache=cache)
    second.clock = lambda: 1_600.0
    result = second.review(request(review_id="another"))
    assert result.model == FREE_MODELS[0]
    assert "skipped during cooldown" in result.fallback_events[0]
    second.clock = lambda: 1_901.0
    assert second.review(request(diff="+different")).provider == "gemini"


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_configuration_and_payment_errors_do_not_silently_fall_through(status: int) -> None:
    script = Script(httpx.Response(status, json={"error": {"message": "configuration"}}))
    with pytest.raises(AIError):
        chain(script).review(request())
    assert len(script.requests) == 1


def test_refusal_is_not_routed_to_another_model() -> None:
    script = Script(ok({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(AIBlockedError):
        chain(script).review(request())
    assert len(script.requests) == 1


def test_schema_repair_failure_does_not_trigger_quota_fallback() -> None:
    script = Script(ok(gemini_body("broken")), ok(gemini_body("still broken")), ok(chat_body(GOOD)))
    with pytest.raises(AIError, match="invalid response twice"):
        chain(script).review(request())
    assert len(script.requests) == 2


def test_all_failed_is_bounded_and_next_request_uses_no_network_during_cooldown() -> None:
    script = Script(rate_limited(), rate_limited())
    provider = chain(script)
    with pytest.raises(AIError, match="No AI provider available"):
        provider.review(request())
    assert len(script.requests) == 2
    with pytest.raises(AIError, match="skipped during cooldown"):
        provider.review(request())
    assert len(script.requests) == 2


def test_network_failure_does_not_trigger_quota_fallback() -> None:
    script = Script(httpx.ConnectError("unreachable"), ok(chat_body(GOOD)))
    with pytest.raises(AIError, match="cannot reach"):
        chain(script).review(request())
    assert len(script.requests) == 1


def test_fix_generation_uses_the_same_chain_and_contract() -> None:
    script = Script(rate_limited(), ok(chat_body(FIX)))
    finding = FixRequest(
        finding_title="bug",
        finding_explanation="wrong",
        category=Category.BUG,
        file="a.py",
        line_start=1,
        line_end=1,
        files={"a.py": "x"},
    )
    result = chain(script).generate_fix(finding)
    assert result.payload.edits[0].replace == "y"
    assert result.model == FREE_MODELS[0] and result.fallback_events


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "glm-5.3-flash", "unknown-free"])
def test_free_adapter_rejects_paid_or_unapproved_ids_before_network(model: str) -> None:
    script = Script()
    provider = OpenCodeFreeProvider(model, transport=script.transport)
    with pytest.raises(AIConfigurationError):
        provider.review(request())
    assert not script.requests


@pytest.mark.parametrize("options", [{"api_key": ""}, {"base_url": "https://other.invalid"}])
def test_free_adapter_requires_local_auth_and_rejects_remote_endpoints(
    options: dict[str, str],
) -> None:
    script = Script()
    provider = OpenCodeFreeProvider(FREE_MODELS[0], transport=script.transport, **options)
    with pytest.raises(AIConfigurationError):
        provider.review(request())
    assert not script.requests


def test_settings_round_trip_and_fallback_is_explicit(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    save_user_setting("provider", "gemini", config)
    save_user_setting("free_fallback", "true", config)
    settings = load_settings(config, env={})
    assert settings.free_fallback
    assert settings.resolved_model == "gemini-3.8-flash"
    save_user_setting("free_fallback", "false", config)
    assert not load_settings(config, env={}).free_fallback


def test_free_provider_uses_only_its_separate_local_token(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path / "absent.toml",
        env={
            "SENTINEL_PROVIDER": "opencode",
            "SENTINEL_OPENCODE_TOKEN": "local-token",
        },
    )
    script = Script(ok(chat_body(GOOD)))
    provider = create_provider(settings, transport=script.transport)
    assert provider is not None and provider.review(request()).model == FREE_MODELS[0]
    assert script.requests[0].headers["authorization"] == "Bearer local-token"


def test_other_providers_remain_standalone_with_gemini_fallback_enabled(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path / "absent.toml", env={"SENTINEL_PROVIDER": "ollama", "SENTINEL_FREE_FALLBACK": "1"}
    )
    provider = create_provider(settings)
    assert provider is not None and not isinstance(provider, FallbackProvider)
    assert provider.name == "ollama"
    provider.close()


@pytest.mark.parametrize("value", ["nan", "inf", "-9", "garbage"])
def test_retry_after_does_not_allow_invalid_sleep_or_cooldown(value: str) -> None:
    assert _retry_after_seconds(httpx.Response(429, headers={"retry-after": value})) == 0


def test_retry_after_accepts_http_date() -> None:
    deadline = format_datetime(datetime.now(UTC) + timedelta(minutes=5), usegmt=True)
    delay = _retry_after_seconds(httpx.Response(429, headers={"retry-after": deadline}))
    assert 290 < delay <= 300


def test_gemini_ignores_thought_parts_and_preserves_only_answer_json() -> None:
    body = gemini_body(json.dumps(GOOD))
    body["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "reasoning"})
    script = Script(ok(body))
    assert GeminiProvider("test", transport=script.transport).review(request()).payload.findings
