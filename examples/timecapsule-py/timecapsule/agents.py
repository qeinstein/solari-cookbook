"""Agent interfaces used by the isolated cloud runner."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from .openrouter import OpenRouterRouter


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


class OpenRouterAgent:
    """Model-backed collections decision maker; model calls stay host-side."""

    def __init__(self, router: OpenRouterRouter, fixed: bool = False):
        self.router = router
        self.fixed = fixed

    async def decide(
        self,
        observation: dict[str, Any],
        future_fingerprint: str,
        environment_fingerprint: str,
    ) -> dict[str, Any]:
        system = (
            "You are the decision policy for a collections workflow. Return only a JSON object "
            "with exactly these keys: action and rationale. action must be send_reminder or suppress. "
            "Keep rationale under 160 characters. Do not invent state."
        )
        if self.fixed:
            system += (
                " The patched policy is conservative: suppress contact whenever the authoritative "
                "payment source says paid or the authoritative dispute source says open. Only send "
                "when both authoritative sources are clear and the CRM invoice is overdue."
            )
        else:
            system += (
                " The original policy is intentionally vulnerable: use only the CRM invoice and CRM "
                "dispute mirrors as its decision source. If CRM says overdue and has no open dispute, "
                "send the reminder even when an authoritative source has already changed."
            )
        user = json.dumps({"task": "Choose the next collections action.", "observation": observation}, sort_keys=True)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt_hash = stable_hash(messages)
        observation_hash = stable_hash(observation)
        completion = await self.router.complete(messages)
        action = completion.response.get("action")
        aliases = {
            "send": "send_reminder",
            "contact": "send_reminder",
            "send_reminder": "send_reminder",
            "suppress": "suppress",
            "wait": "suppress",
            "no_action": "suppress",
        }
        normalized = aliases.get(str(action).strip().lower())
        if normalized is None:
            raise ValueError("OpenRouter action must be send_reminder or suppress")
        return {
            "at": observation.get("at"),
            "action": normalized,
            "route": "send" if normalized == "send_reminder" else "suppress",
            "rationale": str(completion.response.get("rationale", ""))[:160],
            "provider": "openrouter",
            "model": completion.model,
            "requested_model": self.router.requested_model,
            "temperature": self.router.temperature,
            "stochastic": True,
            "prompt_hash": prompt_hash,
            "observation_hash": observation_hash,
            "future_fingerprint": future_fingerprint,
            "environment_fingerprint": environment_fingerprint,
            "model_response": completion.response,
            "request_id": completion.request_id,
            "fallback_from": completion.fallback_from,
        }

    def evidence(self, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "mode": "model",
            "provider": "openrouter",
            "requested_model": self.router.requested_model,
            "active_model": self.router.active_model,
            "temperature": self.router.temperature,
            "stochastic": True,
            "decisions": decisions,
        }
