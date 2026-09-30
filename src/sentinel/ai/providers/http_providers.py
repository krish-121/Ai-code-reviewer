"""Concrete providers: Anthropic Claude, Google Gemini, Ollama. Plain HTTPS via httpx."""

from __future__ import annotations

import json
from typing import Any

from sentinel.ai.providers.base import Completion, HTTPProvider
from sentinel.ai.schemas import strip_nullable
from sentinel.core.domain.models import TokenUsage
from sentinel.core.domain.ports import AIResponseError


class ClaudeProvider(HTTPProvider):
    """Anthropic Messages API. Structured output via a forced tool call."""

    name = "claude"
    default_base_url = "https://api.anthropic.com"
    api_version = "2023-06-01"

    def _complete(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], tool: str
    ) -> Completion:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": messages,
            "tools": [
                {
                    "name": tool,
                    "description": "Submit the result. Always call this tool exactly once.",
                    "input_schema": strip_nullable(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": tool},
        }
        headers = {"x-api-key": self.api_key or "", "anthropic-version": self.api_version}
        data = self._post("/v1/messages", payload, headers)
        usage = data.get("usage") or {}
        text = ""
        for block in data.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == tool:
                text = json.dumps(block.get("input", {}))
                break
            if block.get("type") == "text":
                text += block.get("text", "")
        if not text:
            raise AIResponseError(
                f"claude returned no content (stop_reason={data.get('stop_reason')})"
            )
        return Completion(
            text=text,
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
        )


class GeminiProvider(HTTPProvider):
    """Google Gemini generateContent API with JSON response mode."""

    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com"

    def _complete(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], tool: str
    ) -> Completion:
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        headers = {"x-goog-api-key": self.api_key or ""}
        data = self._post(f"/v1beta/models/{self.model}:generateContent", payload, headers)
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise AIResponseError(f"gemini blocked the prompt: {feedback['blockReason']}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise AIResponseError("gemini returned no candidates")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            reason = candidates[0].get("finishReason", "unknown")
            raise AIResponseError(f"gemini returned an empty answer (finishReason={reason})")
        meta = data.get("usageMetadata") or {}
        return Completion(
            text=text,
            usage=TokenUsage(
                input_tokens=int(meta.get("promptTokenCount", 0)),
                output_tokens=int(meta.get("candidatesTokenCount", 0)),
            ),
        )


class OllamaProvider(HTTPProvider):
    """Local models through Ollama's /api/chat with a JSON-schema ``format``."""

    name = "ollama"
    default_base_url = "http://localhost:11434"

    def _complete(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], tool: str
    ) -> Completion:
        payload = {
            "model": self.model,
            "stream": False,
            "format": strip_nullable(schema),
            "messages": [{"role": "system", "content": system}, *messages],
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        data = self._post("/api/chat", payload, {})
        text = (data.get("message") or {}).get("content", "")
        if not text:
            raise AIResponseError("ollama returned an empty message")
        return Completion(
            text=text,
            usage=TokenUsage(
                input_tokens=int(data.get("prompt_eval_count", 0)),
                output_tokens=int(data.get("eval_count", 0)),
            ),
        )
