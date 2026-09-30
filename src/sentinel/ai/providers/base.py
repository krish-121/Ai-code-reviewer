"""Shared HTTP plumbing for AI providers.

No vendor SDKs: every provider speaks plain HTTPS through ``httpx``. This base class owns
the reliability policy so each provider only describes its wire format:

* 429 / 5xx / 529 -> exponential backoff with jitter, honouring ``Retry-After``
* timeout         -> retry once, then fail clearly
* 401 / 403       -> configuration error (bad key), no retry
* invalid JSON or schema violation -> one retry with a correction message
"""

from __future__ import annotations

import json
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from sentinel.ai.prompts import Prompt, build_fix_prompt, build_review_prompt, correction_message
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
from sentinel.core.domain.ports import AIConfigurationError, AIError, AIResponseError, Cache
from sentinel.infrastructure.storage.cache import content_key

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
P = TypeVar("P", bound=BaseModel)
FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


@dataclass
class Completion:
    text: str
    usage: TokenUsage


class ProviderHTTPError(AIError):
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
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            transport=transport,
            headers={"user-agent": "sentinel-review/0.1"},
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
        attempt = 0
        timeouts = 0
        while True:
            attempt += 1
            self.calls += 1
            try:
                resp = self.client.post(path, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                timeouts += 1
                if timeouts >= 2:
                    raise AIError(
                        f"{self.name} request timed out twice; try again or raise SENTINEL_TIMEOUT"
                    ) from exc
                continue
            except httpx.ConnectError as exc:
                raise AIConfigurationError(
                    f"cannot reach {self.name} at {self.client.base_url}: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIError(f"{self.name} transport error: {exc}") from exc

            if resp.status_code < 400:
                try:
                    return resp.json()
                except json.JSONDecodeError as exc:
                    raise AIResponseError(f"{self.name} returned non-JSON body") from exc
            message = self._error_message(resp)
            if resp.status_code in (401, 403):
                raise AIConfigurationError(
                    f"{self.name} rejected the API key (HTTP {resp.status_code}): {message}"
                )
            if resp.status_code in RETRYABLE_STATUS and attempt <= self.max_retries:
                self.sleep(self._backoff(attempt, resp))
                continue
            if resp.status_code == 429:
                raise AIError(f"{self.name} rate limit persisted after {attempt} attempts")
            raise ProviderHTTPError(resp.status_code, message)

    def _backoff(self, attempt: int, resp: httpx.Response) -> float:
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        base: float = self.backoff_base_s * (2 ** (attempt - 1))
        return min(base + random.uniform(0, base / 2), 30.0)  # noqa: S311 - jitter, not crypto

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except json.JSONDecodeError:
            return resp.text[:300]
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message", err))[:300]
            if isinstance(err, str):
                return err[:300]
        return str(body)[:300]

    # ------------------------------------------------------------------ structured calls
    def _structured(
        self, prompt: Prompt, model_cls: type[P], schema: dict[str, Any], tool: str
    ) -> tuple[P, TokenUsage, int]:
        messages = [{"role": "user", "content": prompt.user}]
        usage = TokenUsage()
        last_error = ""
        for attempt in (1, 2):
            completion = self._complete(prompt.system, messages, schema, tool)
            usage = usage + completion.usage
            try:
                data = extract_json(completion.text)
                return model_cls.model_validate(data), usage, attempt
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = _describe(exc)
                messages = [
                    *messages,
                    {"role": "assistant", "content": completion.text[:4000] or "(empty)"},
                    {"role": "user", "content": correction_message(last_error)},
                ]
        raise AIResponseError(f"{self.name} returned an invalid response twice: {last_error[:300]}")

    def review(self, request: ReviewRequest) -> AIReviewResult:
        prompt = build_review_prompt(request, nonce=_stable_nonce(request.review_id))
        key = content_key(
            "review", self.name, self.model, str(self.temperature), prompt.system, prompt.user
        )
        if self.cache is not None:
            cached = self.cache.get("ai-review", key)
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
            self.cache.set("ai-review", key, result.model_dump_json())
        return result

    def generate_fix(self, request: FixRequest) -> AIFixResult:
        prompt = build_fix_prompt(request)
        payload, usage, attempts = self._structured(prompt, AIFixPayload, FIX_SCHEMA, "submit_fix")
        return AIFixResult(
            payload=payload, usage=usage, model=self.model, provider=self.name, attempts=attempts
        )

    def close(self) -> None:
        self.client.close()


def _stable_nonce(review_id: str) -> str:
    # Deterministic per review so identical requests hit the cache; still unguessable
    # by the code under review because review ids are random.
    return content_key("nonce", review_id)[:16]


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
    return f"invalid JSON: {exc}"
