"""Small OpenRouter-specific client with explicit free-model failover."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import FREE_MODEL_IDS


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenRouterRateLimit(OpenRouterError):
    pass


@dataclass(frozen=True)
class Completion:
    model: str
    response: dict[str, Any]
    request_id: str | None
    fallback_from: str | None = None


def _error_text(body: bytes) -> str:
    try:
        decoded = json.loads(body)
        error = decoded.get("error", decoded)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "OpenRouter request failed")[:500]
        return str(error)[:500]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body.decode(errors="replace")[:500] or "OpenRouter request failed"


def _complete_sync(api_key: str, model: str, messages: list[dict[str, str]], temperature: float) -> Completion:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 160,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/qeinstein/solari-cookbook",
            "X-Title": "TimeCapsule",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            raw = response.read()
    except HTTPError as error:
        body = error.read()
        message = _error_text(body)
        if error.code == 429:
            raise OpenRouterRateLimit(message, error.code) from error
        raise OpenRouterError(message, error.code) from error
    except URLError as error:
        raise OpenRouterError(f"OpenRouter network error: {error.reason}") from error

    try:
        data = json.loads(raw)
        choice = data["choices"][0]["message"]
        content = choice["content"]
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str):
            raise TypeError("model content was not text")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        structured = json.loads(cleaned)
        if not isinstance(structured, dict):
            raise TypeError("model response was not a JSON object")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise OpenRouterError(f"OpenRouter returned an invalid structured response: {error}") from error
    return Completion(
        model=str(data.get("model") or model),
        response=structured,
        request_id=data.get("id"),
    )


class OpenRouterRouter:
    """Share model selection and failover state across concurrent futures."""

    def __init__(self, api_key: str, requested_model: str, temperature: float = 0.2):
        if not 0 <= temperature <= 2:
            raise SystemExit("--temperature must be between 0 and 2")
        self.api_key = api_key
        self.requested_model = requested_model
        self.active_model = requested_model
        self.temperature = temperature
        self.rate_limited: set[str] = set()
        self.fallbacks: list[dict[str, str]] = []
        self._lock = asyncio.Lock()

    def _candidates(self) -> list[str]:
        candidates = [self.active_model]
        for model in FREE_MODEL_IDS:
            if model not in candidates and model not in self.rate_limited:
                candidates.append(model)
        return candidates

    async def complete(self, messages: list[dict[str, str]]) -> Completion:
        async with self._lock:
            previous = self.active_model
            for model in self._candidates():
                try:
                    completion = await asyncio.to_thread(
                        _complete_sync,
                        self.api_key,
                        model,
                        messages,
                        self.temperature,
                    )
                except OpenRouterRateLimit as error:
                    self.rate_limited.add(model)
                    if model not in FREE_MODEL_IDS and not any(candidate in FREE_MODEL_IDS for candidate in self._candidates()[1:]):
                        raise
                    continue
                if model != previous:
                    self.fallbacks.append({"from": previous, "to": model})
                    self.active_model = model
                    return Completion(completion.model, completion.response, completion.request_id, previous)
                return completion
            raise OpenRouterRateLimit("All configured OpenRouter models are currently rate limited", 429)
