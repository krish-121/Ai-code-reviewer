"""Shared HTTP plumbing for AI providers.

No vendor SDKs: every provider speaks plain HTTPS through ``httpx``. This base class owns
the reliability policy so each provider only describes its wire format:

* 429 / 5xx / 529 -> exponential backoff with jitter, honouring ``Retry-After``
* timeout         -> retry once, then fail clearly
* 401 / 403       -> configuration error (bad key), no retry
* invalid JSON or schema violation -> one retry with a correction message

Concrete providers (``http_providers.py``) implement ``_complete``; the factory
(``factory.py``) builds one from settings. The orchestrator only sees the ``AIProvider``
port, never this class.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from sentinel.ai.prompts import (
    Prompt,
    build_fix_prompt,
    build_review_prompt,
    correction_message,
    response_echo,
)
from sentinel.ai.schemas import FIX_SCHEMA, REVIEW_SCHEMA
from sentinel.core.domain.ai import (
    AIFixPayload,
    AIFixResult,
    AIReviewPayload,
    AIReviewResult,
    FixRequest,
    ReviewRequest,
)
from sentinel.core.domain.models import TokenUsage
from sentinel.core.domain.ports import (
    AIBlockedError,
    AIConfigurationError,
    AIConnectionError,
    AIError,
    AIRateLimitError,
    AIResponseError,
    AIUnavailableError,
    Cache,
)
from sentinel.infrastructure.storage.cache import content_key

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
AUTH_FAILURE_STATUS = {401, 403}
RATE_LIMITED = 429
FIRST_ERROR_STATUS = 400
MAX_TIMEOUTS = 2
CONNECT_TIMEOUT_S = 10.0
MAX_RETRY_AFTER_S = 60.0
MAX_BACKOFF_S = 30.0
ERROR_TEXT_LIMIT = 300
MAX_ECHOED_REPLY_CHARS = 4000  # how much of a bad reply is shown back to the model
USER_AGENT = "sentinel-review/0.1"
REVIEW_CACHE_NAMESPACE = "ai-review"
NONCE_LENGTH = 16
P = TypeVar("P", bound=BaseModel)
FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


@dataclass
class Completion:
    """Raw model output (text that should contain JSON) and its token usage."""

    text: str
    usage: TokenUsage


class ProviderHTTPError(AIError):
    """The provider answered with an HTTP error that retrying did not fix."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def extract_json(text: str) -> Any:
    """Parse a JSON object from a model reply, tolerating code fences and leading prose."""
    text = text.strip()
    m = FENCE_RE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class HTTPProvider(ABC):
    """Base class for providers: retries, JSON validation, caching.

    Subclasses only describe their wire format by implementing ``_complete``.
    """

    name: str = "provider"
    default_base_url: str = ""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        cache: Cache | None = None,
        backoff_base_s: float = 1.0,
        trust_env: bool = True,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.sleep = sleep
        self.cache = cache
        self.backoff_base_s = backoff_base_s
        self.client = httpx.Client(
            base_url=base_url or self.default_base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(CONNECT_TIMEOUT_S, timeout_s)),
            transport=transport,
            headers={"user-agent": USER_AGENT},
            trust_env=trust_env,
        )
        self.calls = 0

    # ------------------------------------------------------------------ wire format
    @abstractmethod
    def _complete(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], tool: str
    ) -> Completion:
        """One request to the provider. ``messages`` alternate user/assistant."""

    # ------------------------------------------------------------------ HTTP + retries
    def _post(self, path: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        """POST JSON and return the decoded reply, applying the retry policy above."""
        attempt = 0
        timeouts = 0
        while True:
            attempt += 1
            self.calls += 1
            try:
                response = self.client.post(path, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                timeouts += 1
                if timeouts >= MAX_TIMEOUTS:
                    raise AIUnavailableError(
                        f"{self.name} request timed out twice; try again or raise SENTINEL_TIMEOUT"
                    ) from exc
                continue
            except httpx.HTTPError as exc:
                raise self._transport_error(exc) from exc
            if response.status_code < FIRST_ERROR_STATUS:
                return self._json_body(response)
            if response.status_code in RETRYABLE_STATUS and attempt <= self.max_retries:
                self.sleep(self._backoff(attempt, response))
                continue
            raise self._http_error(response, attempt)

    def _transport_error(self, exc: httpx.HTTPError) -> AIError:
        """Map a network failure to the error type the caller can act on."""
        if isinstance(exc, httpx.ConnectError):
            return AIConnectionError(f"cannot reach {self.name} at {self.client.base_url}: {exc}")
        return AIUnavailableError(f"{self.name} transport error: {exc}")

    def _json_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise AIResponseError(f"{self.name} returned non-JSON body") from exc

    def _http_error(self, response: httpx.Response, attempts: int) -> AIError:
        """The error for a final (non-retried) HTTP failure."""
        message = self._error_message(response)
        if self.api_key:
            pattern = rf"(?<![\w-]){re.escape(self.api_key)}(?![\w-])"
            message = re.sub(pattern, "[redacted]", message)
        if response.status_code in AUTH_FAILURE_STATUS:
            if not self.api_key:
                return AIConfigurationError(
                    f"{self.name} access denied (HTTP {response.status_code}): {message}"
                )
            return AIConfigurationError(
                f"{self.name} rejected the API key (HTTP {response.status_code}): {message}"
            )
        if response.status_code == RATE_LIMITED:
            return AIRateLimitError(
                f"{self.name} rate limit persisted after {attempts} attempts",
                retry_after_s=_retry_after_seconds(response),
            )
        return ProviderHTTPError(response.status_code, message)

    def _backoff(self, attempt: int, resp: httpx.Response) -> float:
        """Seconds to wait: the server's ``Retry-After``, else exponential backoff with jitter."""
        retry_after = _retry_after_seconds(resp)
        if retry_after:
            return min(retry_after, MAX_RETRY_AFTER_S)
        base: float = self.backoff_base_s * (2 ** (attempt - 1))
        return min(base + random.uniform(0, base / 2), MAX_BACKOFF_S)  # noqa: S311 - jitter, not crypto

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        """The provider's error message, from its JSON error body if there is one."""
        try:
            body = resp.json()
        except json.JSONDecodeError:
            return resp.text[:ERROR_TEXT_LIMIT]
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message", err))[:ERROR_TEXT_LIMIT]
            if isinstance(err, str):
                return err[:ERROR_TEXT_LIMIT]
        return str(body)[:ERROR_TEXT_LIMIT]

    # ------------------------------------------------------------------ structured calls
    def _structured(
        self, prompt: Prompt, model_cls: type[P], schema: dict[str, Any], tool: str
    ) -> tuple[P, TokenUsage, int]:
        """Ask for JSON matching ``model_cls``; on a bad reply, retry once with the errors."""
        messages = [{"role": "user", "content": prompt.user}]
        usage = TokenUsage()
        last_error = ""
        for attempt in (1, 2):
            reply = "(invalid provider envelope)"
            try:
                completion = self._complete(prompt.system, messages, schema, tool)
                usage = usage + completion.usage
                reply = completion.text
                data = extract_json(completion.text)
                return model_cls.model_validate(data), usage, attempt
            except AIBlockedError:
                raise
            except (
                AIResponseError,
                json.JSONDecodeError,
                ValidationError,
                KeyError,
                TypeError,
                AttributeError,
                ValueError,
            ) as exc:
                last_error = _describe(exc)
                messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": response_echo(
                            reply[:MAX_ECHOED_REPLY_CHARS] or "(empty)", prompt.nonce
                        ),
                    },
                    {"role": "user", "content": correction_message(last_error, prompt.nonce)},
                ]
        raise AIResponseError(
            f"{self.name} returned an invalid response twice: {last_error[:ERROR_TEXT_LIMIT]}"
        )

    def review(self, request: ReviewRequest) -> AIReviewResult:
        """Review a change. Identical requests are answered from the cache."""
        prompt = build_review_prompt(request, nonce=_stable_nonce(request.review_id))
        semantic = build_review_prompt(request, nonce="CACHE_KEY_ONLY")
        key = content_key(
            "review-v2",
            self.name,
            self.model,
            str(self.temperature),
            str(self.max_tokens),
            semantic.system,
            semantic.user,
        )
        if self.cache is not None:
            cached = self.cache.get(REVIEW_CACHE_NAMESPACE, key)
            if cached is not None:
                result = AIReviewResult.model_validate_json(cached)
                return result.model_copy(update={"cached": True})
        payload, usage, attempts = self._structured(
            prompt, AIReviewPayload, REVIEW_SCHEMA, "submit_review"
        )
        result = AIReviewResult(
            payload=payload, usage=usage, model=self.model, provider=self.name, attempts=attempts
        )
        if self.cache is not None:
            self.cache.set(REVIEW_CACHE_NAMESPACE, key, result.model_dump_json())
        return result

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        """Propose search/replace edits for one finding (never cached)."""
        prompt = build_fix_prompt(request)
        payload, usage, attempts = self._structured(prompt, AIFixPayload, FIX_SCHEMA, "submit_fix")
        return AIFixResult(
            payload=payload, usage=usage, model=self.model, provider=self.name, attempts=attempts
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self.client.close()


def _stable_nonce(review_id: str) -> str:
    """Marker that fences repository content in the prompt (see ``ai/prompts``).

    Deterministic per review so identical requests hit the cache; still unguessable by
    the code under review because review ids are random.
    """
    return content_key("nonce", review_id)[:NONCE_LENGTH]


def _retry_after_seconds(response: httpx.Response) -> float:
    """Interpret seconds or an HTTP date; malformed/non-finite values never reach sleep."""
    value = response.headers.get("retry-after", "")
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            seconds = (deadline - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


def _describe(exc: Exception) -> str:
    """Short, model-readable description of why a reply was rejected."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
    return f"invalid JSON: {exc}"
