from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

import httpx


class LLMProvider(Protocol):
    """Provider contract used by planning and modification stages."""

    def complete(self, *, system: str, user: str, operation: str) -> str: ...


@dataclass
class AIGatewayProvider:
    """OpenAI-compatible client configured exclusively for Vercel AI Gateway."""

    api_key: str | None = None
    base_url: str = "https://ai-gateway.vercel.sh/v1"
    model: str = "openai/gpt-4o-mini"
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "AIGatewayProvider":
        return cls(
            api_key=os.getenv("AI_GATEWAY_API_KEY"),
            base_url=os.getenv("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1").rstrip("/"),
            model=os.getenv("AI_GATEWAY_MODEL", "openai/gpt-4o-mini"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, *, system: str, user: str, operation: str) -> str:
        if not self.api_key:
            raise RuntimeError("AI Gateway is not configured")
        started = time.perf_counter()
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "temperature": 0.1, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        self._log_usage(operation, payload, time.perf_counter() - started)
        return content

    def _log_usage(self, operation: str, payload: dict, latency: float) -> None:
        usage = payload.get("usage", {})
        print(json.dumps({"provider": "ai-gateway", "model": self.model, "operation": operation, "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"), "latency_ms": round(latency * 1000)}))
