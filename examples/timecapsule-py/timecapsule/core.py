from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Callable


INVARIANT_ID = "no_contact_while_external_state_is_stale"
KNOWN_EVENT_KINDS = {
    "invoice_created",
    "customer_payment",
    "payment_webhook",
    "dispute_opened",
    "dispute_webhook",
    "agent_wakeup",
}
EVENT_PRIORITY = {
    "invoice_created": 0,
    "customer_payment": 1,
    "dispute_opened": 2,
    "payment_webhook": 3,
    "dispute_webhook": 4,
    "agent_wakeup": 5,
}


def event_sort_key(event: Event):
    """Make equal-time actions deterministic, including duplicate events."""
    return (
        event.at,
        EVENT_PRIORITY.get(event.kind, len(EVENT_PRIORITY)),
        json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
    )


@dataclass(frozen=True)
class Event:
    at: datetime
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {"at": self.at.isoformat(), "kind": self.kind, "payload": self.payload}


@dataclass
class World:
    now: datetime
    payment_status: str = "unpaid"
    invoice_status: str = "overdue"
    payment_at: datetime | None = None
    webhook_due_at: datetime | None = None
    webhook_scheduled: bool = False
    dispute_status: str = "none"
    crm_dispute_status: str = "none"
    dispute_at: datetime | None = None
    dispute_webhook_due_at: datetime | None = None
    dispute_webhook_scheduled: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, event: Event):
        if event.kind not in KNOWN_EVENT_KINDS:
            raise ValueError(f"unknown event kind: {event.kind}")
        self.now = event.at
        if event.kind == "customer_payment":
            self.payment_status = "paid"
            self.payment_at = event.at
            self.webhook_due_at = event.at + timedelta(hours=event.payload.get("webhook_delay_hours", 0))
        elif event.kind == "payment_webhook":
            self.invoice_status = "paid"
        elif event.kind == "dispute_opened":
            self.dispute_status = "open"
            self.dispute_at = event.at
            self.dispute_webhook_due_at = event.at + timedelta(
                minutes=event.payload.get("webhook_delay_minutes", 0)
            )
        elif event.kind == "dispute_webhook":
            self.crm_dispute_status = "open"
        self.trace.append({"at": event.at.isoformat(), "event": event.as_dict()})


class PolicyAgent:
    def __init__(self, verify_payment_before_contact=False):
        self.verify_payment_before_contact = verify_payment_before_contact

    def wake(self, world: World):
        if world.invoice_status != "overdue" or world.crm_dispute_status == "open":
            return
        if self.verify_payment_before_contact and (
            world.payment_status == "paid" or world.dispute_status == "open"
        ):
            reason = "payment" if world.payment_status == "paid" else "dispute"
            world.trace.append({
                "at": world.now.isoformat(),
                "agent": "verified_source_and_suppressed",
                "reason": reason,
            })
            return
        world.messages.append({
            "at": world.now,
            "type": "collections_reminder",
            "invoice": "INV-1842",
            "payment_status": world.payment_status,
            "invoice_status": world.invoice_status,
            "dispute_status": world.dispute_status,
            "crm_dispute_status": world.crm_dispute_status,
            "payment_webhook_scheduled": world.webhook_scheduled,
            "dispute_webhook_scheduled": world.dispute_webhook_scheduled,
        })
        world.trace.append({"at": world.now.isoformat(), "agent": "sent_overdue_reminder"})


# Kept as a compatibility name for the deterministic local proof and saved
# regression fixtures. New cloud code refers to the implementation as the
# PolicyAgent so the model-backed sibling is explicit.
CollectionsAgent = PolicyAgent


def run_future(events: list[Event], agent: CollectionsAgent) -> World:
    world = World(now=min((event.at for event in events), default=datetime(2026, 9, 1, 9)))
    world.webhook_scheduled = any(event.kind == "payment_webhook" for event in events)
    world.dispute_webhook_scheduled = any(event.kind == "dispute_webhook" for event in events)
    for event in sorted(events, key=event_sort_key):
        world.apply(event)
        if event.kind == "agent_wakeup":
            agent.wake(world)
    return world


def invariant_violations(world: World) -> list[dict[str, Any]]:
    """Return every unsafe contact caused by stale external collections state."""
    violations = []
    for message in world.messages:
        # Evaluate the state captured at the wakeup, not the world's final
        # source timestamps. This remains correct if an adversarial future
        # contains duplicate payments or disputes after the unsafe contact.
        if (
            message.get("payment_webhook_scheduled")
            and message["payment_status"] == "paid"
            and message["invoice_status"] == "overdue"
        ):
            violations.append({
                "type": "stale_payment_contact",
                "title": "Contact after payment",
                "summary": "Payment was settled while the CRM still marked the invoice overdue.",
                "at": message["at"].isoformat(),
                "source_label": "Payment system",
                "source_value": "PAID",
                "mirror_label": "CRM invoice",
                "mirror_value": message["invoice_status"].upper(),
                "agent_belief": message["invoice_status"].upper(),
                "message": "Your payment remains overdue.",
            })
        if (
            message.get("dispute_webhook_scheduled")
            and message["dispute_status"] == "open"
            and message["crm_dispute_status"] != "open"
        ):
            violations.append({
                "type": "active_dispute_contact",
                "title": "Contact during an active dispute",
                "summary": "A dispute was open while the CRM still considered the invoice collectible.",
                "at": message["at"].isoformat(),
                "source_label": "Dispute service",
                "source_value": "OPEN",
                "mirror_label": "CRM dispute",
                "mirror_value": message["crm_dispute_status"].upper(),
                "agent_belief": "COLLECTIBLE",
                "message": "Your payment remains overdue.",
            })
    return violations


def invariant_holds(world: World) -> bool:
    """No collections contact while payment or dispute state is stale."""
    return not invariant_violations(world)


def violation_snapshot(world: World) -> dict[str, Any] | None:
    violations = invariant_violations(world)
    return violations[0] if violations else None


def generate_future(seed: int, start=datetime(2026, 9, 1, 9)) -> list[Event]:
    """Generate a deterministic mix of safe and unsafe collection timelines."""
    rng = random.Random(seed)
    payment_day = rng.randint(1, 4)
    delay = rng.choice([0, 2, 6, 12, 24, 36, 72])
    wake_count = rng.choice([1, 2, 2, 3])
    wake_offsets = sorted(rng.sample([-24, -6, 0, 3, 9, 18, 30, 54, 84], wake_count))
    payment = start + timedelta(days=payment_day)
    events = [
        Event(start, "invoice_created"),
        Event(payment, "customer_payment", {"webhook_delay_hours": delay}),
        Event(payment + timedelta(hours=delay), "payment_webhook"),
        *(Event(payment + timedelta(hours=offset), "agent_wakeup") for offset in wake_offsets),
    ]
    return sorted(events, key=event_sort_key)


def temporal_windows(events: list[Event]) -> set[str]:
    payment = next((event for event in events if event.kind == "customer_payment"), None)
    webhook = next((event for event in events if event.kind == "payment_webhook"), None)
    if payment is None or webhook is None:
        return set()
    windows = set()
    for wake in (event for event in events if event.kind == "agent_wakeup"):
        if wake.at < payment.at:
            windows.add("before_payment")
        elif wake.at < webhook.at:
            windows.add("stale_window")
        else:
            windows.add("after_webhook")
    return windows


def future_fingerprint(events: list[Event]) -> str:
    encoded = json.dumps(
        [event.as_dict() for event in sorted(events, key=event_sort_key)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def observed_violations(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations = []
    for item in trace:
        if not str(item.get("action", "")).startswith("agent/") or not item.get("sent"):
            continue
        if (
            item.get("payment") == "paid"
            and item.get("crm") == "overdue"
            and item.get("webhook_scheduled", True)
        ):
            violations.append({
                "type": "stale_payment_contact",
                "title": "Contact after payment",
                "summary": "Payment was settled while the CRM still marked the invoice overdue.",
                "at": item.get("at"),
                "source_label": "Payment system",
                "source_value": "PAID",
                "mirror_label": "CRM invoice",
                "mirror_value": "OVERDUE",
                "agent_belief": "OVERDUE",
                "message": "Your payment remains overdue.",
            })
        if (
            item.get("dispute") == "open"
            and item.get("crm_dispute") != "open"
            and item.get("dispute_webhook_scheduled", True)
        ):
            violations.append({
                "type": "active_dispute_contact",
                "title": "Contact during an active dispute",
                "summary": "A dispute was open while the CRM still considered the invoice collectible.",
                "at": item.get("at"),
                "source_label": "Dispute service",
                "source_value": "OPEN",
                "mirror_label": "CRM dispute",
                "mirror_value": str(item.get("crm_dispute", "none")).upper(),
                "agent_belief": "COLLECTIBLE",
                "message": "Your payment remains overdue.",
            })
    return violations


def observed_violation(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    violations = observed_violations(trace)
    return violations[0] if violations else None


def observed_invariant_holds(trace: list[dict[str, Any]]) -> bool:
    return observed_violation(trace) is None


def execute(events: list[Event], fixed=False) -> World:
    return run_future(events, CollectionsAgent(verify_payment_before_contact=fixed))


def minimize(events: list[Event], predicate: Callable[[list[Event]], bool] | None = None) -> list[Event]:
    predicate = predicate or (lambda candidate: not invariant_holds(execute(candidate)))
    current = list(events)
    changed = True
    while changed:
        changed = False
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1:]
            if predicate(candidate):
                current, changed = candidate, True
                break
    return current


def minimize_for_violation(
    events: list[Event],
    failure_type: str | None = None,
) -> list[Event]:
    """Delta-debug an input without changing which invariant failure it demonstrates."""
    original_types = [item["type"] for item in invariant_violations(execute(events))]
    target = failure_type or (original_types[0] if original_types else None)
    if target is None or target not in original_types:
        return list(events)
    return minimize(
        events,
        lambda candidate: any(
            item["type"] == target
            for item in invariant_violations(execute(candidate))
        ),
    )


def comparison(events: list[Event]):
    return {"original": "PASS" if invariant_holds(execute(events)) else "FAIL",
            "patched": "PASS" if invariant_holds(execute(events, fixed=True)) else "FAIL"}


def save_future(path: Path, events: list[Event], result=None):
    computed = comparison(events)
    if result is not None and result != computed:
        raise ValueError(f"supplied regression result {result} does not match {computed}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"events": [event.as_dict() for event in sorted(events, key=event_sort_key)], "result": computed}, indent=2) + "\n")


def load_future(path: Path) -> list[Event]:
    data = json.loads(path.read_text())
    return [Event(datetime.fromisoformat(item["at"]), item["kind"], item.get("payload", {})) for item in data["events"]]
