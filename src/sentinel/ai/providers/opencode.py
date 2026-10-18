"""Free DeepSeek through the isolated local bridge to official OpenCode.

The factory wires this adapter into Gemini's quota fallback. It keeps Sentinel's
existing prompt/schema/cache policy while the bridge owns the CLI process inside
Docker. Only a separate local bearer token goes to the bridge, never a Gemini key.
"""

from __future__ import annotations

from typing import Any

from sentinel.ai.providers.base import Completion, HTTPProvider
from sentinel.core.configuration.config import Settings
from sentinel.core.domain.models import TokenUsage
from sentinel.core.domain.ports import AIConfigurationError, AIResponseError

FREE_MODELS = ("deepseek-v4.1-flash-free",)
OPENCODE_URL = "http://127.0.0.1:4097"
CHAT_PATH = "/complete"
BRIDGE_MAX_TOKENS = 4096


class OpenCodeFreeProvider(HTTPProvider):
    """Use only the approved free ID and a local, authenticated bridge."""

    name = "opencode"
    default_base_url = OPENCODE_URL

    def _complete(
        self, system: str, messages: list[dict[str, str]], schema: dict[str, Any], tool: str
    ) -> Completion:
        if self.model not in FREE_MODELS:
            raise AIConfigurationError("Only deepseek-v4.1-flash-free is approved")
        try:
            Settings(opencode_url=str(self.client.base_url))
        except ValueError as exc:
            raise AIConfigurationError("OpenCode requires the local bridge URL") from exc
        if not self.api_key:
            raise AIConfigurationError("Local OpenCode bridge token is not configured")
        prompt = (
            system
            + "\n\n"
            + "\n\n".join(f"{message['role']}:\n{message['content']}" for message in messages)
        )
        prompt += "\nUse the supplied text only. Do not call tools or access files."
        data = self._post(
            CHAT_PATH,
            {
                "model": self.model,
                "prompt": prompt,
                "max_tokens": min(self.max_tokens, BRIDGE_MAX_TOKENS),
                "temperature": self.temperature,
            },
            {"Authorization": f"Bearer {self.api_key}"},
        )
        if data.get("model") != self.model:
            raise AIResponseError("OpenCode bridge returned an unexpected model")
        choice = data["choices"][0]
        text = choice["message"]["content"]
        if choice.get("finish_reason") != "stop" or not isinstance(text, str) or not text.strip():
            raise AIResponseError("OpenCode bridge returned no finished text response")
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            usage=TokenUsage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
        )
