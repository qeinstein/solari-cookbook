"""Counterfactual manifests that prove environment inputs stayed identical."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .core import Event, event_sort_key, future_fingerprint


WORLD_CONTRACT = "collections-world-v2"
INITIAL_STATE = {
    "payment": "unpaid",
    "crm_invoice": "overdue",
    "dispute": "none",
    "crm_dispute": "none",
    "messages": [],
}
INVOICE_FIXTURE = {
    "invoice_id": "INV-1842",
    "customer": "Northstar Labs",
    "amount_usd": 12000,
    "due_at": "2026-08-31T23:59:59",
}
POLICIES = {
    "original": "trust_crm_only",
    "fixed": "verify_payment_and_dispute_sources",
}
EXAMPLE_ROOT = Path(__file__).parents[1]


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def world_asset_hash() -> str:
    digest = hashlib.sha256()
    for path in (EXAMPLE_ROOT / "world/server.py", EXAMPLE_ROOT / "world/index.html"):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def environment_manifest(events: list[Event], policy: str) -> dict[str, Any]:
    canonical_events = sorted(events, key=event_sort_key)
    inputs = {
        "world_contract": WORLD_CONTRACT,
        "world_asset_hash": world_asset_hash(),
        "initial_state": INITIAL_STATE,
        "invoice_fixture": INVOICE_FIXTURE,
        "events": [event.as_dict() for event in canonical_events],
    }
    return {
        "environment_hash": _hash(inputs),
        "event_hash": future_fingerprint(events),
        "world_contract": WORLD_CONTRACT,
        "world_asset_hash": inputs["world_asset_hash"],
        "invoice_id": INVOICE_FIXTURE["invoice_id"],
        "initial_state_hash": _hash(INITIAL_STATE),
        "fixture_hash": _hash(INVOICE_FIXTURE),
        "event_count": len(events),
        "agent_policy": POLICIES[policy],
    }


def counterfactual_proof(events: list[Event]) -> dict[str, Any]:
    original = environment_manifest(events, "original")
    patched = environment_manifest(events, "fixed")
    identical = [
        "environment_hash",
        "event_hash",
        "world_contract",
        "world_asset_hash",
        "invoice_id",
        "initial_state_hash",
        "fixture_hash",
        "event_count",
    ]
    differing = [key for key in original if original[key] != patched[key]]
    return {
        "verified": all(original[key] == patched[key] for key in identical)
        and differing == ["agent_policy"],
        "identical_fields": identical,
        "differing_fields": differing,
        "only_change": {
            "field": "agent_policy",
            "original": original["agent_policy"],
            "patched": patched["agent_policy"],
        },
        "original": original,
        "patched": patched,
    }
