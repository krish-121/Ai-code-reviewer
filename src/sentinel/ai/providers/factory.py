"""Provider registry. Adding a provider = one class + one entry in ``PROVIDERS``."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from sentinel.ai.providers.base import HTTPProvider
from sentinel.ai.providers.fallback import FallbackProvider
from sentinel.ai.providers.http_providers import ClaudeProvider, GeminiProvider, OllamaProvider
from sentinel.ai.providers.opencode import FREE_MODELS, OpenCodeFreeProvider
from sentinel.core.configuration.config import KEY_ENV_VARS, Settings
from sentinel.core.domain.ports import AIConfigurationError, AIProvider, Cache
from sentinel.infrastructure.storage.cache import DiskCache

PROVIDERS: dict[str, type[HTTPProvider]] = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "opencode": OpenCodeFreeProvider,
}
NEEDS_KEY = {"claude", "gemini", "opencode"}


def missing_key_message(provider: str) -> str:
    """A helpful error naming the environment variable that holds the key."""
    if provider == "opencode":
        return "Local OpenCode bridge token missing. Run python scripts/opencode_bridge.py start."
    env = KEY_ENV_VARS.get(provider, (f"SENTINEL_{provider.upper()}_KEY",))[0]
    return (
        f"{provider.capitalize()} API key not configured.\n"
        f"Run `sentinel config set {provider}_api_key <key>` or set {env}."
    )


def create_provider(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    cache: Cache | None = None,
    sleep: Callable[[float], None] | None = None,
) -> AIProvider | None:
    """Build one adapter or the explicit Gemini-quota -> free DeepSeek chain."""
    if settings.provider == "none":
        return None
    if settings.provider != "gemini":
        # This preference belongs to Gemini; choosing another provider stays standalone.
        settings = settings.model_copy(update={"free_fallback": False})
    if settings.provider == "opencode" and settings.resolved_model not in FREE_MODELS:
        raise AIConfigurationError(f"OpenCode model must be one of {', '.join(FREE_MODELS)}")
    if settings.free_fallback:
        cache = cache if cache is not None else DiskCache(settings.cache_dir)
    primary = _single_provider(settings, transport=transport, cache=cache, sleep=sleep)
    if not settings.free_fallback:
        return primary
    assert cache is not None
    secondaries = [
        _single_provider(
            settings.model_copy(update={"provider": "opencode", "model": model}),
            transport=transport,
            cache=cache,
            sleep=sleep,
        )
        for model in FREE_MODELS
    ]
    return FallbackProvider(
        [primary, *secondaries], cache=cache, cooldown_s=settings.fallback_cooldown_s
    )


def _single_provider(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None,
    cache: Cache | None,
    sleep: Callable[[float], None] | None,
) -> HTTPProvider:
    """Use no HTTP retry before quota fallback; the local bridge bypasses proxies."""
    cls = PROVIDERS.get(settings.provider)
    if cls is None:
        raise AIConfigurationError(f"unknown provider {settings.provider!r}")
    key = settings.api_key_for(settings.provider)
    if settings.provider in NEEDS_KEY and not key:
        raise AIConfigurationError(missing_key_message(settings.provider))
    kwargs: dict[str, object] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return cls(
        settings.resolved_model,
        api_key=key,
        base_url={"ollama": settings.ollama_url, "opencode": settings.opencode_url}.get(
            settings.provider
        ),
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout_s=settings.timeout_s,
        max_retries=0 if settings.free_fallback else settings.max_retries,
        transport=transport,
        cache=cache,
        trust_env=settings.provider != "opencode",
        **kwargs,  # type: ignore[arg-type]
    )
