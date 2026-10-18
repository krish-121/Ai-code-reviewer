"""Use free DeepSeek when Gemini reports quota exhaustion, outside the core engine.

The factory creates this AIProvider decorator when fallback is explicitly enabled.
Each request gets one pass through the chain. Quota failures temporarily open
a circuit in the shared cache; other errors and refusals remain visible.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import TypeVar

from sentinel.ai.providers.base import HTTPProvider
from sentinel.core.domain.ai import AIFixResult, AIReviewResult, FixRequest, ReviewRequest
from sentinel.core.domain.ports import (
    AIBlockedError,
    AIError,
    AIRateLimitError,
    Cache,
)
from sentinel.infrastructure.storage.cache import content_key

CIRCUIT_NAMESPACE = "ai-provider-cooldown"
MAX_COOLDOWN_S = 86_400.0
R = TypeVar("R", AIReviewResult, AIFixResult)


class FallbackProvider:
    """A bounded provider chain with a credential-specific, best-effort cooldown."""

    name = "fallback"

    def __init__(
        self,
        providers: list[HTTPProvider],
        *,
        cache: Cache,
        cooldown_s: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not providers:
            raise ValueError("fallback needs at least one provider")
        self.providers = providers
        self.model = " -> ".join(provider.model for provider in providers)
        self.cache = cache
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._until: dict[str, float] = {}

    def review(self, request: ReviewRequest) -> AIReviewResult:
        """Review through the first available provider; retain the actual winner."""
        return self._run(lambda provider: provider.review(request))

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        """Use the same chain; the fix engine still validates every proposed edit."""
        return self._run(lambda provider: provider.generate_fix(request))

    def _run(self, operation: Callable[[HTTPProvider], R]) -> R:
        events: list[str] = []
        for provider in self.providers:
            label = f"{provider.name}/{provider.model}"
            key = self._key(provider)
            if self._cooling_down(key):
                events.append(f"{label}: skipped during cooldown")
                continue
            try:
                result = operation(provider)
            except AIBlockedError:
                raise  # A refusal is not a reason to try to bypass it elsewhere.
            except AIError as exc:
                reason = _fallback_reason(exc)
                if reason is None:
                    raise  # Only explicit quota errors can switch providers.
                events.append(f"{label}: {reason}")
                self._open_circuit(key, exc)
                continue
            return result.model_copy(update={"fallback_events": events})
        raise AIError("No AI provider available. " + "; ".join(events))

    def _key(self, provider: HTTPProvider) -> str:
        return content_key(
            "cooldown-v1",
            provider.name,
            provider.model,
            str(provider.client.base_url),
            provider.api_key or "anonymous",
        )

    def _cooling_down(self, key: str) -> bool:
        stored = self.cache.get(CIRCUIT_NAMESPACE, key)
        try:
            until = max(self._until.get(key, 0.0), float(stored or "0"))
        except ValueError:
            until = self._until.get(key, 0.0)
        return math.isfinite(until) and until > self.clock()

    def _open_circuit(self, key: str, error: AIError) -> None:
        retry_after = error.retry_after_s if isinstance(error, AIRateLimitError) else 0.0
        delay = min(max(self.cooldown_s, retry_after), MAX_COOLDOWN_S)
        until = self.clock() + delay
        self._until[key] = until
        self.cache.set(CIRCUIT_NAMESPACE, key, str(until))

    def close(self) -> None:
        """Release all connection pools when the owning review/fix service finishes."""
        for provider in self.providers:
            provider.close()


def _fallback_reason(error: AIError) -> str | None:
    """Only an explicit quota/rate limit permits switching providers."""
    if isinstance(error, AIRateLimitError):
        return "rate limit reached"
    return None
