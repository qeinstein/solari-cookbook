from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Callable


INVARIANT_ID = "no_contact_during_stale_payment_window"
KNOWN_EVENT_KINDS = {"invoice_created", "customer_payment", "payment_webhook", "agent_wakeup"}


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
        self.trace.append({"at": event.at.isoformat(), "event": event.as_dict()})


class CollectionsAgent:
    def __init__(self, verify_payment_before_contact=False):
        self.verify_payment_before_contact = verify_payment_before_contact

    def wake(self, world: World):
        if world.invoice_status != "overdue":
            return
        if self.verify_payment_before_contact and world.payment_status == "paid":
            world.trace.append({"at": world.now.isoformat(), "agent": "verified_paid_and_suppressed"})
            return
        world.messages.append({
            "at": world.now,
            "type": "collections_reminder",
            "invoice": "INV-1842",
            "payment_status": world.payment_status,
            "invoice_status": world.invoice_status,
        })
        world.trace.append({"at": world.now.isoformat(), "agent": "sent_overdue_reminder"})


def run_future(events: list[Event], agent: CollectionsAgent) -> World:
    world = World(now=min((event.at for event in events), default=datetime(2026, 9, 1, 9)))
    world.webhook_scheduled = any(event.kind == "payment_webhook" for event in events)
    for event in sorted(events, key=lambda event: event.at):
        world.apply(event)
        if event.kind == "agent_wakeup":
            agent.wake(world)
    return world


def invariant_holds(world: World) -> bool:
    """No collections contact after payment before the expected webhook."""
    if not world.webhook_scheduled or world.payment_at is None or world.webhook_due_at is None:
        return True
    return not any(world.payment_at <= message["at"] < world.webhook_due_at for message in world.messages)


def violation_snapshot(world: World) -> dict[str, Any] | None:
    if world.payment_at is None or world.webhook_due_at is None:
        return None
    message = next((
        message for message in world.messages
        if world.payment_at <= message["at"] < world.webhook_due_at
    ), None)
    if message is None:
        return None
    return {
        "at": message["at"].isoformat(),
        "payment_status": message["payment_status"].upper(),
        "crm_status": message["invoice_status"].upper(),
        "agent_belief": message["invoice_status"].upper(),
        "message": "Your payment remains overdue.",
    }


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
    return sorted(events, key=lambda event: event.at)


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
        [event.as_dict() for event in events],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def observed_violation(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    payment_seen = False
    webhook_seen = False
    for item in trace:
        action = item.get("action")
        if action == "pay":
            payment_seen = True
        elif action == "webhook":
            webhook_seen = True
        elif action in {"agent/original", "agent/fixed"} and item.get("sent"):
            if payment_seen and not webhook_seen:
                return {
                    "payment_status": str(item.get("payment", "paid")).upper(),
                    "crm_status": str(item.get("crm", "overdue")).upper(),
                    "agent_belief": str(item.get("crm", "overdue")).upper(),
                    "message": "Your payment remains overdue.",
                }
    return None


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


def comparison(events: list[Event]):
    return {"original": "PASS" if invariant_holds(execute(events)) else "FAIL",
            "patched": "PASS" if invariant_holds(execute(events, fixed=True)) else "FAIL"}


def save_future(path: Path, events: list[Event], result=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"events": [event.as_dict() for event in events], "result": result or comparison(events)}, indent=2) + "\n")


def load_future(path: Path) -> list[Event]:
    data = json.loads(path.read_text())
    return [Event(datetime.fromisoformat(item["at"]), item["kind"], item.get("payload", {})) for item in data["events"]]
