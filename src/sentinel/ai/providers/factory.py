"""Provider registry. Adding a provider = one class + one entry in ``PROVIDERS``."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from sentinel.ai.providers.base import HTTPProvider
from sentinel.ai.providers.http_providers import ClaudeProvider, GeminiProvider, OllamaProvider
from sentinel.core.configuration.config import KEY_ENV_VARS, Settings
from sentinel.core.domain.ports import AIConfigurationError, AIProvider, Cache

PROVIDERS: dict[str, type[HTTPProvider]] = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}
NEEDS_KEY = {"claude", "gemini"}


def missing_key_message(provider: str) -> str:
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
    """Return the configured provider, or None for deterministic-only reviews."""
    if settings.provider == "none":
        return None
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
        base_url=settings.ollama_url if settings.provider == "ollama" else None,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout_s=settings.timeout_s,
        max_retries=settings.max_retries,
        transport=transport,
        cache=cache,
        **kwargs,  # type: ignore[arg-type]
    )
