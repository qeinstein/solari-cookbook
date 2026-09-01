from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
from typing import Any, Callable


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
        world.messages.append({"at": world.now, "type": "collections_reminder", "invoice": "INV-1842"})
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


def generate_future(seed: int, start=datetime(2026, 9, 1, 9)) -> list[Event]:
    rng = random.Random(seed)
    payment_day = rng.randint(1, 4)
    delay = rng.choice([0, 6, 12, 36])
    wake_day = rng.randint(payment_day, payment_day + 2)
    payment = start + timedelta(days=payment_day)
    return sorted([
        Event(start, "invoice_created"),
        Event(payment, "customer_payment", {"webhook_delay_hours": delay}),
        Event(payment + timedelta(hours=delay), "payment_webhook"),
        Event(start + timedelta(days=wake_day), "agent_wakeup"),
    ], key=lambda event: event.at)


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
