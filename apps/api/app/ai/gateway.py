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
class AIGatewayCompletion:
    """A single model response plus the usage the gateway reported, if any."""

    content: str
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int = 0


@dataclass
class AIGatewayProvider:
    """OpenAI-compatible client configured exclusively for Vercel AI Gateway.

    The key, base URL and model all come from configuration; no credential or
    model name is hardcoded here. The model can be changed with
    `AI_GATEWAY_MODEL` without touching any caller.
    """

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
            timeout_seconds=float(os.getenv("AI_GATEWAY_TIMEOUT", "60")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, *, system: str, user: str, operation: str) -> str:
        """Backwards-compatible text-only entry point."""
        return self.complete_detailed(system=system, user=user, operation=operation).content

    def complete_detailed(self, *, system: str, user: str, operation: str) -> AIGatewayCompletion:
        """Same call, but also returns token usage and latency for cost tracking."""
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
        usage = payload.get("usage", {}) or {}
        latency_ms = round((time.perf_counter() - started) * 1000)
        completion = AIGatewayCompletion(
            content=content,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
        )
        self._log_usage(operation, payload, latency_ms)
        return completion

    def _log_usage(self, operation: str, payload: dict, latency: float) -> None:
        usage = payload.get("usage", {})
        print(json.dumps({"provider": "ai-gateway", "model": self.model, "operation": operation, "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"), "latency_ms": round(latency * 1000)}))
